"""文件廢止申請（US8 / UCDM05 / DM02）整合測試（真實 DB）。

涵蓋：發起廢止（→ PENDING_OBSOLETE + OBSOLETE review + OBS_SUBMIT 通知、附件落地 OBSOLETE_FILE_*）、
發起檢核（缺原因 DM_DOC_014 / 缺審核者 DM_DOC_015 / 選自己 DM_REVIEW_001 / 文件非已發布 DM_DOC_016 /
同時新版本送審 DM_REVIEW_002 / 附件格式 DM_FILE_002）、待簽核仍在架、核准（→ OBSOLETE + DM_CHANGE_LOG(OBSOLETE)
+ OBS_APPROVE）、退回（→ PUBLISHED + OBS_REJECT）、廢止附件下載授權（Q1=C：admin / 指定審核者可、發起人 403）、
HTTP 存取閘（401 / 403）。
"""

import os

import pytest
from sqlalchemy import select, text

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.obsolete.service import ObsoleteService
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.models import DmChangeLog, DmReview
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = ObsoleteService()
_rsvc = ReviewCenterService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp，避免污染工作目錄（廢止附件 save_upload / 下載共用）。"""
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid="ed"):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, user_id, name, email=None):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email or f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _audience_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _add_version(db, doc_id, version_no, *, status, author="ed", published=None):
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name=f"{version_no}.pdf",
        file_path=os.path.join(storage_root(), doc_id, f"{version_no}.pdf"),
        file_size=100,
        file_mime=_PDF,
        status=status,
        published_date=published,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    return v


async def _doc(db, doc_id, *, status, current_version_id=None, author="ed", audience=()):
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=f"文件{doc_id}",
        category_code="SOP",
        current_version_id=current_version_id,
        status=status,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    for n in audience:
        db.add(DmDocTag(doc_id=doc_id, tag_id=await _audience_id(db, n), created_user=author, created_date=utcnow()))
    await db.flush()
    return doc


async def _published_doc(db, doc_id, *, author="ed", audience=("全體",)):
    """已發布文件 + 目前發布版（供發起廢止）。"""
    doc = await _doc(db, doc_id, status="PUBLISHED", author=author, audience=audience)
    v = await _add_version(db, doc_id, "1.0", status="PUBLISHED", author=author, published=utcnow())
    doc.current_version_id = v.version_id
    await db.flush()
    return doc, v


async def _email_count(db, template_code, recipient):
    # 限 STATUS='PENDING'：範本渲染失敗（缺 param key）會寫 STATUS='FAILED' + 空內容，若不篩會把失敗誤計為成功。
    return await db.scalar(
        text(
            'SELECT count(*) FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE"=:t AND "RECIPIENT"=:r AND "STATUS"=\'PENDING\''
        ).bindparams(t=template_code, r=recipient)
    )


# ── 發起廢止 ──────────────────────────────────────────


async def test_initiate_transits_pending_obsolete_and_notifies(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, _ = await _published_doc(db, "DM-SOP-000401")

    result = await _svc.initiate(
        db,
        doc_id="DM-SOP-000401",
        reason="流程已停辦",
        reviewer_id="rev1",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("ed"),
    )

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000401"))
    review = await db.scalar(select(DmReview).where(DmReview.review_id == result.review_id))
    assert doc.status == "PENDING_OBSOLETE"  # 轉廢止待簽核（FR-002）
    assert review.review_type == "OBSOLETE" and review.status == "PENDING"
    assert review.assigned_reviewer == "rev1" and review.reason == "流程已停辦"
    assert result.doc_status == "PENDING_OBSOLETE"
    assert result.notified == 1  # 成功排入（渲染成功；渲染失敗 queued_count 會是 0）
    assert await _email_count(db, "OBS_SUBMIT", "rev1@e.com") == 1  # 通知指定審核者（STATUS=PENDING）
    # 內容驗證：確認 params key 對齊範本佔位（渲染成功、非空信）——堵住「author_name vs applicant_name」類回歸
    body = await db.scalar(
        text('SELECT "BODY" FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE"=\'OBS_SUBMIT\' AND "RECIPIENT"=\'rev1@e.com\'')
    )
    assert body and "流程已停辦" in body and "文件DM-SOP-000401" in body


async def test_initiate_with_attachment_saves_obsolete_file(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _published_doc(db, "DM-SOP-000402")

    result = await _svc.initiate(
        db,
        doc_id="DM-SOP-000402",
        reason="停辦函文",
        reviewer_id="rev1",
        file_name="停辦函文.pdf",
        file_bytes=b"%PDF-1.4 letter",
        file_mime=_PDF,
        op=_op("ed"),
    )

    review = await db.scalar(select(DmReview).where(DmReview.review_id == result.review_id))
    assert review.obsolete_file_name == "停辦函文.pdf" and review.obsolete_file_size == len(b"%PDF-1.4 letter")
    assert review.obsolete_file_path and os.path.isfile(review.obsolete_file_path)  # 實體落地於 storage root


async def test_initiate_missing_reason_blocked(db):
    await _published_doc(db, "DM-SOP-000403")
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000403",
            reason="  ",
            reviewer_id="rev1",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_DOC_014"  # DM-MSG-DM02-011


async def test_initiate_missing_reviewer_blocked(db):
    await _published_doc(db, "DM-SOP-000404")
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000404",
            reason="停辦",
            reviewer_id="",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_DOC_015"  # DM-MSG-DM02-014


async def test_initiate_reviewer_is_self_blocked(db):
    await _published_doc(db, "DM-SOP-000405")
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000405",
            reason="停辦",
            reviewer_id="ed",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_REVIEW_001"  # 不可自審自核


async def test_initiate_non_published_doc_blocked(db):
    # 草稿文件不可發起廢止
    await _doc(db, "DM-SOP-000406", status="DRAFT", audience=("全體",))
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000406",
            reason="停辦",
            reviewer_id="rev1",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_DOC_016"


async def test_initiate_blocked_when_new_version_in_review(db):
    # 文件已發布且另有進行中之新版本送審（一文件一 PENDING）→ 無法同時發起廢止（FR-004 / DM-MSG-DM02-012）
    doc, _ = await _published_doc(db, "DM-SOP-000407")
    nv = await _add_version(db, "DM-SOP-000407", "2.0", status="PENDING_REVIEW")
    db.add(
        DmReview(
            doc_id="DM-SOP-000407",
            version_id=nv.version_id,
            review_type="NEW_VERSION",
            assigned_reviewer="rev1",
            status="PENDING",
            submit_date=utcnow(),
            created_user="ed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000407",
            reason="停辦",
            reviewer_id="rev1",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_REVIEW_002"


async def test_initiate_invalid_attachment_format_blocked(db):
    await _published_doc(db, "DM-SOP-000408")
    with pytest.raises(AppError) as e:
        await _svc.initiate(
            db,
            doc_id="DM-SOP-000408",
            reason="停辦",
            reviewer_id="rev1",
            file_name="evil.exe",
            file_bytes=b"MZ",
            file_mime="application/octet-stream",
            op=_op("ed"),
        )
    assert e.value.error_code == "DM_FILE_002"
    # 檢核未過 → 不建立 review、文件維持已發布
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000408"))
    assert doc.status == "PUBLISHED"
    assert await db.scalar(select(DmReview).where(DmReview.doc_id == "DM-SOP-000408")) is None


# ── 核准 / 退回（延伸 US6 簽核中心）──────────────────────


async def _pending_obsolete(db, doc_id, *, reason="停辦", reviewer="rev1"):
    """已發布文件發起廢止後之狀態（review PENDING OBSOLETE + doc PENDING_OBSOLETE）。"""
    await _published_doc(db, doc_id)
    result = await _svc.initiate(
        db,
        doc_id=doc_id,
        reason=reason,
        reviewer_id=reviewer,
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("ed"),
    )
    return result.review_id


async def test_approve_obsolete_transits_document_obsolete(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    review_id = await _pending_obsolete(db, "DM-SOP-000411")

    await _rsvc.approve(db, review_id=review_id, op=_op("rev1"))

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000411"))
    review = await db.scalar(select(DmReview).where(DmReview.review_id == review_id))
    cur = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == doc.current_version_id))
    assert doc.status == "OBSOLETE"  # 文件已廢止、自文件庫下架
    assert doc.current_version_id is not None and cur.status == "PUBLISHED"  # 保留發布版（SRVDM001 廢止旗標）
    assert review.status == "APPROVED" and review.reason == "停辦"  # 核准不覆寫廢止原因
    log = await db.scalar(
        select(DmChangeLog).where(DmChangeLog.doc_id == "DM-SOP-000411", DmChangeLog.operation == "OBSOLETE")
    )
    assert log is not None and log.note == "停辦"  # 變更歷程廢止事件、NOTE=廢止原因
    assert await _email_count(db, "OBS_APPROVE", "ed@e.com") == 1  # 通知撰寫者


async def test_reject_obsolete_restores_published(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    review_id = await _pending_obsolete(db, "DM-SOP-000412")

    await _rsvc.reject(db, review_id=review_id, reason="仍需沿用", op=_op("rev1"))

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000412"))
    review = await db.scalar(select(DmReview).where(DmReview.review_id == review_id))
    assert doc.status == "PUBLISHED"  # 退回 → 回已發布
    assert review.status == "REJECTED"
    assert await _email_count(db, "OBS_REJECT", "ed@e.com") == 1


# ── 廢止附件下載授權（SA 裁示 Q1=C）──────────────────────


async def _obsolete_with_file(db, doc_id):
    result = await _svc.initiate(
        db,
        doc_id=doc_id,
        reason="停辦函文",
        reviewer_id="rev1",
        file_name="letter.pdf",
        file_bytes=b"%PDF-1.4 letter",
        file_mime=_PDF,
        op=_op("ed"),
    )
    return result.review_id


async def test_obsolete_file_download_authz(db):
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _published_doc(db, "DM-SOP-000421")
    review_id = await _obsolete_with_file(db, "DM-SOP-000421")

    # 指定審核者可下載
    served = await _rsvc.prepare_obsolete_file(db, review_id=review_id, roles=[DM_REVIEWER], op=_op("rev1"))
    assert os.path.isfile(served.path) and served.name == "letter.pdf"
    # DM_ADMIN 可下載（即使非指定審核者）
    served2 = await _rsvc.prepare_obsolete_file(db, review_id=review_id, roles=[DM_ADMIN], op=_op("admin1"))
    assert os.path.isfile(served2.path)
    # 發起人本人不可（Q1=C）
    with pytest.raises(AppError) as e1:
        await _rsvc.prepare_obsolete_file(db, review_id=review_id, roles=[DM_EDITOR], op=_op("ed"))
    assert e1.value.error_code == "DM_REVIEW_005"
    # 一般閱覽者不可
    with pytest.raises(AppError) as e2:
        await _rsvc.prepare_obsolete_file(db, review_id=review_id, roles=[DM_VIEWER], op=_op("viewer1"))
    assert e2.value.error_code == "DM_REVIEW_005"


# ── HTTP 存取閘 ──────────────────────────────────────


async def test_http_initiate_requires_auth(db, client):
    resp = await client.post("/api/dm/documents/DM-SOP-000431/obsolete", data={"reason": "x", "reviewer_id": "rev1"})
    assert resp.status_code == 401


async def test_http_initiate_forbidden_without_editor_role(db, client):
    await _seed_user(db, "viewer1", "純閱覽")
    await _grant(db, "viewer1", DM_VIEWER)  # 有 DM 角色但非編輯者
    token = create_access_token(sub="viewer1", ttl_minutes=15)
    resp = await client.post(
        "/api/dm/documents/DM-SOP-000432/obsolete",
        headers={"Authorization": f"Bearer {token}"},
        data={"reason": "停辦", "reviewer_id": "rev1"},
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"


async def test_http_download_published_version_during_pending_obsolete(db, client):
    """item 二：廢止待簽核期間，詳細頁仍可下載目前發布版（需實體檔存在）。"""
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _seed_user(db, "ed2", "編輯", email="ed2@e.com")
    await _grant(db, "ed2", DM_EDITOR)
    doc, v = await _published_doc(db, "DM-SOP-000441", author="ed2")
    os.makedirs(os.path.dirname(v.file_path), exist_ok=True)  # 寫實體版本檔（下載端 is_file 檢查）
    with open(v.file_path, "wb") as f:
        f.write(b"%PDF-1.4 doc")
    await _svc.initiate(
        db,
        doc_id="DM-SOP-000441",
        reason="停辦",
        reviewer_id="rev1",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("ed2"),
    )
    token = create_access_token(sub="ed2", ttl_minutes=15)
    resp = await client.get(
        f"/api/dm/documents/DM-SOP-000441/versions/{v.version_id}/file",
        params={"disposition": "download"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200 and resp.content == b"%PDF-1.4 doc"


async def test_http_upload_then_download_obsolete_attachment(db, client):
    """item 六：完整前端路徑——編輯者以 multipart 上傳廢止附件 → 指定審核者於 DM04 下載（HTTP 全鏈路）。"""
    await _seed_user(db, "ed3", "編輯", email="ed3@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _grant(db, "ed3", DM_EDITOR)
    await _grant(db, "rev1", DM_REVIEWER)
    await _published_doc(db, "DM-SOP-000442", author="ed3")
    # 發起（multipart 含附件）——模擬 DmObsoleteDialog 送出
    ed_token = create_access_token(sub="ed3", ttl_minutes=15)
    post = await client.post(
        "/api/dm/documents/DM-SOP-000442/obsolete",
        headers={"Authorization": f"Bearer {ed_token}"},
        data={"reason": "院內停辦", "reviewer_id": "rev1"},
        files={"file": ("停辦函文.pdf", b"%PDF-1.4 letter", _PDF)},
    )
    assert post.status_code == 200
    review_id = post.json()["review_id"]
    # 指定審核者下載
    rev_token = create_access_token(sub="rev1", ttl_minutes=15)
    resp = await client.get(
        f"/api/dm/reviews/{review_id}/obsolete-file",
        headers={"Authorization": f"Bearer {rev_token}"},
    )
    assert resp.status_code == 200 and resp.content == b"%PDF-1.4 letter"
    # 發起人本人不可下載（Q1=C）
    forbidden = await client.get(
        f"/api/dm/reviews/{review_id}/obsolete-file",
        headers={"Authorization": f"Bearer {ed_token}"},
    )
    assert forbidden.status_code == 403


async def test_http_initiate_multipart_success(db, client):
    await _seed_user(db, "editor1", "編輯者")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _grant(db, "editor1", DM_EDITOR)
    await _published_doc(db, "DM-SOP-000433", author="editor1")
    token = create_access_token(sub="editor1", ttl_minutes=15)
    resp = await client.post(
        "/api/dm/documents/DM-SOP-000433/obsolete",
        headers={"Authorization": f"Bearer {token}"},
        data={"reason": "流程停辦", "reviewer_id": "rev1"},
        files={"file": ("letter.pdf", b"%PDF-1.4 x", _PDF)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_status"] == "PENDING_OBSOLETE" and body["review_id"] > 0
