"""US5 編輯器續編草稿（#222）整合測試（真實 DB）。

涵蓋：draft-meta 讀端點（首版草稿 / 新版本草稿皆可載 meta + 既有 DRAFT 版本內容、退回草稿預帶前次審核者、
非本人 404）、續編更新既有 DRAFT 版本（in-place 不新增列 / 不撞唯一索引、父 DRAFT 可改名 [Q1=A]、
父已發布名稱唯讀、非草稿 409 / 非本人 403）。
"""

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.editor.service import EditorService
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = EditorService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp。"""
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid="ed"):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, user_id, user_name, email=None):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email or f"{user_id}@e.com",
            pwd_hash="x",
            user_name=user_name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _audience_id(db, name="全體"):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _first_version_draft(db, *, name="首版草稿文件", version_no="1.0", summary="首版摘要"):
    """建一份首版草稿（文件 DRAFT + 首版 DRAFT，作者 ed）。"""
    aud = await _audience_id(db)
    return await _svc.create_document(
        db,
        doc_name=name,
        category_code="SOP",
        func_code=None,
        audience_ids=[aud],
        retrieval_ids=[],
        version_no=version_no,
        change_summary=summary,
        file_name="a.pdf",
        file_bytes=b"%PDF-1.4 x",
        file_mime=_PDF,
        op=_op(),
    )


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _obsolete_with_draft(db, doc_id, *, author="ed"):
    """建一份已廢止(OBSOLETE)文件 + 作者之 DRAFT 孤兒版本。"""
    now = utcnow()
    doc = DmDocument(
        doc_id=doc_id,
        doc_name="已廢止文件",
        category_code="SOP",
        current_version_id=None,
        status="OBSOLETE",
        created_user=author,
        created_date=now,
    )
    db.add(doc)
    await db.flush()
    ver = DmDocVersion(
        doc_id=doc_id,
        version_no="2.0",
        change_summary="孤兒草稿",
        file_name="o.pdf",
        file_path="/x/o.pdf",
        file_size=10,
        file_mime=_PDF,
        status="DRAFT",
        created_user=author,
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    return doc, ver


async def _published_with_draft_newversion(db, doc_id, *, author="ed"):
    """建一份已發布文件 + 作者之 DRAFT 新版本（模擬新版本草稿續編情境）。"""
    now = utcnow()
    # 先建文件（current_version_id 暫 None）→ 建版本 → 回填 current_version_id，避免 FK 循環
    doc = DmDocument(
        doc_id=doc_id,
        doc_name="已發布文件",
        category_code="SOP",
        current_version_id=None,
        status="PUBLISHED",
        created_user=author,
        created_date=now,
    )
    db.add(doc)
    await db.flush()
    cur = DmDocVersion(
        doc_id=doc_id,
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_path="/x/v1.pdf",
        file_size=100,
        file_mime=_PDF,
        status="PUBLISHED",
        published_date=now,
        created_user=author,
        created_date=now,
    )
    db.add(cur)
    await db.flush()
    doc.current_version_id = cur.version_id
    nv = DmDocVersion(
        doc_id=doc_id,
        version_no="2.0-draft",
        change_summary="新版草稿摘要",
        file_name="v2.pdf",
        file_path="/x/v2.pdf",
        file_size=200,
        file_mime=_PDF,
        status="DRAFT",
        created_user=author,
        created_date=now,
    )
    db.add(nv)
    await db.flush()
    return doc, cur, nv


# ── draft-meta 讀端點 ────────────────────────────────


async def test_draft_meta_first_version_returns_meta_and_content(db):
    await _seed_user(db, "ed", "撰寫")
    r = await _first_version_draft(db)
    meta = await _svc.get_draft_meta(db, doc_id=r.doc_id, user_id="ed")
    assert meta.doc_status == "DRAFT" and meta.name_editable is True  # 首版草稿名稱可改（Q1=A）
    assert meta.doc_name == "首版草稿文件" and meta.category_code == "SOP"
    assert meta.draft_version_id == r.version_id
    assert meta.version_no == "1.0" and meta.change_summary == "首版摘要"
    assert meta.file_name == "a.pdf" and meta.previewable is True
    assert meta.assigned_reviewer is None  # 從未送審 → 無前次審核者


async def test_draft_meta_new_version_draft_readonly_name(db):
    await _seed_user(db, "ed", "撰寫")
    _, _, nv = await _published_with_draft_newversion(db, "DM-SOP-000900")
    meta = await _svc.get_draft_meta(db, doc_id="DM-SOP-000900", user_id="ed")
    assert meta.doc_status == "PUBLISHED" and meta.name_editable is False  # 已發布文件之新版草稿名稱唯讀
    assert meta.draft_version_id == nv.version_id
    assert meta.version_no == "2.0-draft" and meta.change_summary == "新版草稿摘要"


async def test_draft_meta_non_owner_404(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "other", "他人")
    r = await _first_version_draft(db)
    with pytest.raises(AppError) as e:
        await _svc.get_draft_meta(db, doc_id=r.doc_id, user_id="other")
    assert e.value.status_code == 404


async def test_draft_meta_prefills_last_reviewer_when_rejected(db):
    await _seed_user(db, "ed", "撰寫")
    r = await _first_version_draft(db)
    # 該版本曾送審被退回 → 預帶前次指定審核者
    db.add(
        DmReview(
            doc_id=r.doc_id,
            version_id=r.version_id,
            review_type="NEW",
            assigned_reviewer="rev1",
            status="REJECTED",
            submit_date=utcnow(),
            complete_date=utcnow(),
            created_user="ed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    meta = await _svc.get_draft_meta(db, doc_id=r.doc_id, user_id="ed")
    assert meta.assigned_reviewer == "rev1"


# ── 續編更新既有 DRAFT 版本 ─────────────────────────


async def test_update_draft_version_in_place_no_new_row(db):
    await _seed_user(db, "ed", "撰寫")
    r = await _first_version_draft(db)
    aud = await _audience_id(db)
    before = await db.scalar(select(func.count()).select_from(DmDocVersion).where(DmDocVersion.doc_id == r.doc_id))
    res = await _svc.update_draft_version(
        db,
        doc_id=r.doc_id,
        version_id=r.version_id,
        doc_name=None,
        audience_ids=[aud],
        retrieval_ids=[],
        version_no="1.1",
        change_summary="續編修訂",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op(),
    )
    after = await db.scalar(select(func.count()).select_from(DmDocVersion).where(DmDocVersion.doc_id == r.doc_id))
    assert res.version_id == r.version_id and after == before  # in-place：版本數不變、無另開
    ver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == r.version_id))
    assert ver.version_no == "1.1" and ver.change_summary == "續編修訂"


async def test_update_draft_version_updates_doc_name_when_parent_draft(db):
    # Q1=A：父文件 DRAFT（首版草稿）續編可改文件名稱
    await _seed_user(db, "ed", "撰寫")
    r = await _first_version_draft(db)
    aud = await _audience_id(db)
    await _svc.update_draft_version(
        db,
        doc_id=r.doc_id,
        version_id=r.version_id,
        doc_name="改過的名稱",
        audience_ids=[aud],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版摘要",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op(),
    )
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert doc.doc_name == "改過的名稱"


async def test_update_draft_version_ignores_doc_name_when_published(db):
    # 父文件已發布（新版本草稿）→ 名稱唯讀，送 doc_name 不生效
    await _seed_user(db, "ed", "撰寫")
    _, _, nv = await _published_with_draft_newversion(db, "DM-SOP-000901")
    aud = await _audience_id(db)
    await _svc.update_draft_version(
        db,
        doc_id="DM-SOP-000901",
        version_id=nv.version_id,
        doc_name="想改但不該生效",
        audience_ids=[aud],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改摘要",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op(),
    )
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000901"))
    assert doc.doc_name == "已發布文件"  # 未被改寫


async def test_update_draft_version_non_draft_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    _, cur, _ = await _published_with_draft_newversion(db, "DM-SOP-000902")
    aud = await _audience_id(db)
    with pytest.raises(AppError) as e:
        await _svc.update_draft_version(
            db,
            doc_id="DM-SOP-000902",
            version_id=cur.version_id,  # PUBLISHED 版本
            doc_name=None,
            audience_ids=[aud],
            retrieval_ids=[],
            version_no="9.9",
            change_summary="x",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op(),
        )
    assert e.value.status_code == 409


async def test_update_draft_version_non_owner_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "other", "他人")
    r = await _first_version_draft(db)
    aud = await _audience_id(db)
    with pytest.raises(AppError) as e:
        await _svc.update_draft_version(
            db,
            doc_id=r.doc_id,
            version_id=r.version_id,
            doc_name=None,
            audience_ids=[aud],
            retrieval_ids=[],
            version_no="1.1",
            change_summary="x",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op("other"),
        )
    assert e.value.status_code == 403


async def test_update_draft_version_rename_requires_doc_owner(db):
    # security MEDIUM：改名（改 DM_DOCUMENT.doc_name 跨版本共享欄）限文件建立者；
    # 他人於同份 DRAFT 文件另開自己版本者，續編自己版本可、但不得改文件名稱（忽略、不生效）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "other", "他人")
    r = await _first_version_draft(db)  # 文件 + 首版皆 ed 建立
    now = utcnow()
    ov = DmDocVersion(
        doc_id=r.doc_id,
        version_no="1.0-b",
        change_summary="b",
        file_name="b.pdf",
        file_path="/x/b.pdf",
        file_size=10,
        file_mime=_PDF,
        status="DRAFT",
        created_user="other",  # other 於 ed 的 DRAFT 文件另開自己的草稿版本
        created_date=now,
    )
    db.add(ov)
    await db.flush()
    aud = await _audience_id(db)
    await _svc.update_draft_version(
        db,
        doc_id=r.doc_id,
        version_id=ov.version_id,
        doc_name="他人想改名",
        audience_ids=[aud],
        retrieval_ids=[],
        version_no="1.0-b",
        change_summary="b",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("other"),
    )
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert doc.doc_name == "首版草稿文件"  # 非文件建立者改名不生效


async def test_update_draft_version_blocked_when_doc_obsolete(db):
    # HIGH(review)：父文件已廢止(OBSOLETE 終態)之孤兒草稿不得續編（僅可刪除）；後端擋 DM_DOC_018
    await _seed_user(db, "ed", "撰寫")
    _, ver = await _obsolete_with_draft(db, "DM-SOP-000910")
    aud = await _audience_id(db)
    with pytest.raises(AppError) as e:
        await _svc.update_draft_version(
            db,
            doc_id="DM-SOP-000910",
            version_id=ver.version_id,
            doc_name=None,
            audience_ids=[aud],
            retrieval_ids=[],
            version_no="2.1",
            change_summary="想續編",
            file_name=None,
            file_bytes=None,
            file_mime=None,
            op=_op(),
        )
    assert e.value.error_code == "DM_DOC_018"


async def test_submit_blocked_when_doc_obsolete(db):
    # HIGH(review) 延伸：已廢止文件之孤兒草稿亦不得送簽（_ensure_submittable 擋 DM_DOC_018）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, ver = await _obsolete_with_draft(db, "DM-SOP-000911")
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id="DM-SOP-000911", version_id=ver.version_id, assigned_reviewer="rev1", op=_op())
    assert e.value.error_code == "DM_DOC_018"


# ── HTTP 授權閘（新端點）───────────────────────────


async def test_http_draft_meta_forbidden_without_editor(db, client):
    # 新端點掛 _ensure_editor：具 DM 角色但非編輯者 → 403 DM_AUTH_002
    await _seed_user(db, "v", "閱覽")
    await _grant(db, "v", DM_VIEWER)
    token = create_access_token(sub="v", ttl_minutes=15)
    resp = await client.get(
        "/api/dm/editor/documents/DM-SOP-000001/draft-meta", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"


async def test_http_update_draft_forbidden_without_editor(db, client):
    await _seed_user(db, "v", "閱覽")
    await _grant(db, "v", DM_VIEWER)
    token = create_access_token(sub="v", ttl_minutes=15)
    resp = await client.put(
        "/api/dm/documents/DM-SOP-000001/versions/1",
        headers={"Authorization": f"Bearer {token}"},
        data={"version_no": "1.1", "change_summary": "x"},
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"


async def test_http_draft_meta_requires_auth(db, client):
    resp = await client.get("/api/dm/editor/documents/DM-SOP-000001/draft-meta")
    assert resp.status_code == 401
