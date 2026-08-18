"""文件新增與編輯（US5 / DM03）整合測試（真實 DB）。

涵蓋 8 條 AC：新增 + DOC_ID 配號（循序遞增）、必填 / 分類 / 標籤檢核、MANUAL func 條件式必填、
編輯新版本（身份欄不吃 / 單一草稿 / 廢止待簽核擋 / 版號重複 / IntegrityError 並發後盾映射）、
送簽（建 review + 狀態轉移 + 通知 + 稽核 + 可見對象≥1 / func 唯一 / 審核者排除撰寫者本人 /
單一 PENDING）、reviewer 下拉排除自己、表單受控下拉、存取閘（HTTP 401 / 403）與 multipart 落盤。
"""

import pytest
from sqlalchemy import func, select, text

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmFunc, DmTag
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.editor.service import EditorService
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = EditorService()

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp，避免污染工作目錄。"""
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


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _audience_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _make_retrieval_tag(db, name, group="NATURE"):
    t = DmTag(tag_group_code=group, tag_name=name, created_user="seed", created_date=utcnow())
    db.add(t)
    await db.flush()
    return t.tag_id


async def _make_func(db, code, name):
    db.add(DmFunc(func_code=code, func_name=name, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _create(
    db,
    *,
    op=None,
    category="SOP",
    func_code=None,
    audience=("全體",),
    retrieval=(),
    name="領血SOP",
    version_no="1.0",
    mime=_PDF,
    summary="首版",
):
    """呼叫 service.create_document 之精簡包裝（audience 以名稱轉 id）。"""
    aud_ids = [await _audience_id(db, n) for n in audience]
    return await _svc.create_document(
        db,
        doc_name=name,
        category_code=category,
        func_code=func_code,
        audience_ids=aud_ids,
        retrieval_ids=list(retrieval),
        version_no=version_no,
        change_summary=summary,
        file_name="a.pdf" if mime == _PDF else "a.docx",
        file_bytes=b"%PDF-1.4 x" if mime == _PDF else b"PK\x03\x04 x",
        file_mime=mime,
        op=op or _op(),
    )


# ── AC1/3：新增 + DOC_ID 配號 ─────────────────────────


async def test_create_assigns_doc_id_and_draft(db):
    r = await _create(db, retrieval=[await _make_retrieval_tag(db, "平時")])
    assert r.doc_id == "DM-SOP-000001" and r.previewable is True
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert doc.status == "DRAFT" and doc.doc_name == "領血SOP"
    ver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == r.version_id))
    assert ver.status == "DRAFT" and ver.version_no == "1.0"
    # 標籤：1 可見對象 + 1 檢索
    n = await db.scalar(
        select(func.count()).select_from(DmDocTag).where(DmDocTag.doc_id == r.doc_id, DmDocTag.deleted == 0)
    )
    assert n == 2


async def test_doc_id_sequence_increments_per_category(db):
    r1 = await _create(db, name="A")
    r2 = await _create(db, name="B")
    assert (r1.doc_id, r2.doc_id) == ("DM-SOP-000001", "DM-SOP-000002")


async def test_create_missing_required_blocked(db):
    with pytest.raises(AppError) as e:
        await _create(db, name="   ")
    assert e.value.status_code == 422 and e.value.error_code == "DM_DOC_004"


async def test_create_invalid_category_blocked(db):
    with pytest.raises(AppError) as e:
        await _create(db, category="NOPE")
    assert e.value.error_code == "DM_DOC_010"


# ── AC2/7：MANUAL func 條件式必填 ─────────────────────


async def test_create_manual_requires_func(db):
    with pytest.raises(AppError) as e:
        await _create(db, category="MANUAL", func_code=None)
    assert e.value.error_code == "DM_DOC_004"


async def test_create_manual_with_func_ok(db):
    await _make_func(db, "F001", "領血作業")
    r = await _create(db, category="MANUAL", func_code="F001", name="領血手冊")
    assert r.doc_id == "DM-MANUAL-000001"
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert doc.func_code == "F001"


async def test_create_nonmanual_ignores_func(db):
    await _make_func(db, "F002", "x")
    r = await _create(db, category="SOP", func_code="F002")
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert doc.func_code is None  # 非手冊類不吃 func


# ── AC5：Office 上傳 previewable 旗標 ─────────────────


async def test_create_office_not_previewable(db):
    r = await _create(db, mime=_DOCX)
    assert r.previewable is False


# ── 標籤群組驗證 ──────────────────────────────────────


async def test_create_wrong_group_tag_blocked(db):
    """檢索標籤 id 誤放入可見對象 → DM_DOC_010。"""
    rid = await _make_retrieval_tag(db, "法規X", group="LEGAL")
    aud_all = await _audience_id(db, "全體")
    with pytest.raises(AppError) as e:
        await _svc.create_document(
            db,
            doc_name="d",
            category_code="SOP",
            func_code=None,
            audience_ids=[rid],
            retrieval_ids=[aud_all],  # 兩者群組相反
            version_no="1.0",
            change_summary="s",
            file_name="a.pdf",
            file_bytes=b"x",
            file_mime=_PDF,
            op=_op(),
        )
    assert e.value.error_code == "DM_DOC_010"


# ── AC4：編輯新版本 ───────────────────────────────────


async def _publish_doc(db, doc_id, *, category="SOP", func_code=None, author="ed", audience=("全體",)):
    """建立一份已發布文件（含目前版 + 可見對象），供編輯新版本測試。"""
    doc = DmDocument(
        doc_id=doc_id,
        doc_name="已發布",
        category_code=category,
        func_code=func_code,
        current_version_id=None,
        status="PUBLISHED",
        created_user=author,
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    v = DmDocVersion(
        doc_id=doc_id,
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_path="/x/v1.pdf",
        file_size=10,
        file_mime=_PDF,
        status="PUBLISHED",
        published_date=utcnow(),
        created_user=author,
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    doc.current_version_id = v.version_id
    for n in audience:
        db.add(DmDocTag(doc_id=doc_id, tag_id=await _audience_id(db, n), created_user=author, created_date=utcnow()))
    await db.flush()
    return doc


async def _add_version(db, doc_id, *, version_no="2.0", op=None, mime=_PDF):
    return await _svc.add_version(
        db,
        doc_id=doc_id,
        version_no=version_no,
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 y",
        file_mime=mime,
        op=op or _op(),
    )


async def test_add_version_creates_draft_keeps_doc_published(db):
    await _publish_doc(db, "DM-SOP-000100")
    r = await _add_version(db, "DM-SOP-000100", version_no="2.0")
    ver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == r.version_id))
    assert ver.status == "DRAFT" and ver.version_no == "2.0"
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000100"))
    assert doc.status == "PUBLISHED"  # 已發布文件之新版草稿不動文件狀態


async def test_add_version_inherits_doc_tags_untouched(db):
    """新版本沿用文件既有標籤、不動可見性（避免草稿期靜默清空已發布文件標籤）。"""
    await _publish_doc(db, "DM-SOP-000101", audience=("全體",))
    await _add_version(db, "DM-SOP-000101", version_no="2.0")
    active = await db.scalars(
        select(DmTag.tag_name)
        .join(DmDocTag, DmDocTag.tag_id == DmTag.tag_id)
        .where(DmDocTag.doc_id == "DM-SOP-000101", DmDocTag.deleted == 0)
    )
    assert set(active.all()) == {"全體"}  # 標籤原封不動


@pytest.mark.parametrize(
    ("taken_side_effect", "expected"),
    [([False, True], "DM_DOC_006"), ([False, False], "DM_DOC_009")],
)
async def test_add_version_integrity_race_maps_friendly(db, monkeypatch, taken_side_effect, expected):
    """並發後盾：實際 INSERT 撞 DB 約束（IntegrityError）→ 回退後重查映射友善錯誤（版號重複 / 單一草稿）。"""
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import IntegrityError

    await _publish_doc(db, "DM-SOP-000110")

    async def _boom(*a, **k):
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(_svc._repo, "add_version", _boom)
    # 前置 version_no_taken 回 False（過檢核）；except 內重查依情境回 False/True
    monkeypatch.setattr(_svc._repo, "version_no_taken", AsyncMock(side_effect=taken_side_effect))
    with pytest.raises(AppError) as e:
        await _add_version(db, "DM-SOP-000110", version_no="2.0")
    assert e.value.error_code == expected


async def test_add_version_duplicate_version_no_blocked(db):
    await _publish_doc(db, "DM-SOP-000102")
    with pytest.raises(AppError) as e:
        await _add_version(db, "DM-SOP-000102", version_no="1.0")  # 與目前版重號
    assert e.value.error_code == "DM_DOC_006"


async def test_add_version_single_draft_blocked(db):
    await _publish_doc(db, "DM-SOP-000103")
    await _add_version(db, "DM-SOP-000103", version_no="2.0")  # 第一個草稿
    with pytest.raises(AppError) as e:
        await _add_version(db, "DM-SOP-000103", version_no="3.0")  # 已有未送簽草稿
    assert e.value.error_code == "DM_DOC_009"


async def test_add_version_pending_obsolete_blocked(db):
    await _publish_doc(db, "DM-SOP-000104")
    db.add(
        DmReview(
            doc_id="DM-SOP-000104",
            review_type="OBSOLETE",
            assigned_reviewer="rev",
            status="PENDING",
            submit_date=utcnow(),
            created_user="applicant",
            created_date=utcnow(),
        )
    )
    await db.flush()
    with pytest.raises(AppError) as e:
        await _add_version(db, "DM-SOP-000104", version_no="2.0")
    assert e.value.error_code == "DM_DOC_008"


# ── AC6/AC8：送簽 ─────────────────────────────────────


async def _prep_submit(db, doc_id, *, reviewer="rev1", author="ed", audience=("全體",)):
    await _seed_user(db, author, "陳撰寫")
    await _seed_user(db, reviewer, "王審核", email="rev@e.com")
    await _grant(db, reviewer, DM_REVIEWER)
    r = await _create(db, op=_op(author), name="送簽SOP", audience=audience)
    return r


async def test_submit_new_creates_review_and_transitions_and_notifies(db):
    r = await _prep_submit(db, "x")
    res = await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert res.review_id is not None and res.notified == 1
    review = await db.scalar(select(DmReview).where(DmReview.review_id == res.review_id))
    assert review.review_type == "NEW" and review.status == "PENDING" and review.assigned_reviewer == "rev1"
    ver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == r.version_id))
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == r.doc_id))
    assert ver.status == "PENDING_REVIEW" and doc.status == "PENDING_REVIEW"
    # 已排入 Email outbox
    n = await db.scalar(
        text('SELECT count(*) FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE"=\'DOC_SUBMIT\' AND "RECIPIENT"=\'rev@e.com\'')
    )
    assert n == 1


async def test_submit_new_version_keeps_doc_published(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev@e.com")
    await _grant(db, "rev1", DM_REVIEWER)
    await _publish_doc(db, "DM-SOP-000200", author="ed")
    v = await _add_version(db, "DM-SOP-000200", version_no="2.0", op=_op("ed"))
    res = await _svc.submit(db, doc_id="DM-SOP-000200", version_id=v.version_id, assigned_reviewer="rev1", op=_op("ed"))
    review = await db.scalar(select(DmReview).where(DmReview.review_id == res.review_id))
    assert review.review_type == "NEW_VERSION"
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000200"))
    assert doc.status == "PUBLISHED"  # 版本層 PENDING，文件維持已發布


async def test_submit_without_audience_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev@e.com")
    await _grant(db, "rev1", DM_REVIEWER)
    r = await _create(db, op=_op("ed"), name="無可見對象", audience=())  # 不掛可見對象
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert e.value.error_code == "DM_DOC_005"


async def test_submit_reviewer_is_author_blocked(db):
    r = await _prep_submit(db, "x")
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="ed", op=_op("ed"))
    assert e.value.error_code == "DM_REVIEW_001"


async def test_submit_reviewer_is_version_author_blocked_even_if_other_submits(db):
    """代送情境：他人（editor B）代送 A 撰寫之草稿，指派 A 為審核者 → 仍擋（排除撰寫者本人）。"""
    await _seed_user(db, "A", "撰寫者A")
    await _seed_user(db, "B", "代送者B")
    await _grant(db, "A", DM_REVIEWER)
    r = await _create(db, op=_op("A"), name="A的草稿", audience=("全體",))  # 版本 CREATED_USER = A
    with pytest.raises(AppError) as e:
        # B 送簽、指派 A（實際撰寫者）為審核者 → 擋
        await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="A", op=_op("B"))
    assert e.value.error_code == "DM_REVIEW_001"


async def test_submit_manual_func_conflict_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev@e.com")
    await _grant(db, "rev1", DM_REVIEWER)
    await _make_func(db, "F900", "衝突作業")
    # 既有一份已發布之同 func 手冊
    other = DmDocument(
        doc_id="DM-MANUAL-000900",
        doc_name="既有手冊",
        category_code="MANUAL",
        func_code="F900",
        current_version_id=None,
        status="PUBLISHED",
        created_user="ed",
        created_date=utcnow(),
    )
    db.add(other)
    await db.flush()
    r = await _create(db, op=_op("ed"), category="MANUAL", func_code="F900", name="新手冊")
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert e.value.error_code == "DM_DOC_007"


async def test_submit_twice_blocked_by_single_pending(db):
    r = await _prep_submit(db, "x")
    await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert e.value.error_code == "DM_REVIEW_002"


# ── reviewer 下拉 + options ───────────────────────────


async def test_list_reviewers_excludes_self(db):
    await _seed_user(db, "me", "我")
    await _seed_user(db, "r1", "審核一")
    await _seed_user(db, "r2", "審核二")
    await _grant(db, "me", DM_REVIEWER)
    await _grant(db, "r1", DM_REVIEWER)
    await _grant(db, "r2", DM_REVIEWER)
    got = await _svc.list_reviewers(db, op=_op("me"))
    ids = {x.user_id for x in got}
    assert ids == {"r1", "r2"}  # 排除自己


async def test_writes_are_audited(db):
    """新增 / 加版 / 送簽皆寫 DP_AUDIT_LOG（MODULE=DM、FUNC=DM-EDITOR、target=DOC_ID）。"""
    r = await _prep_submit(db, "x")  # create（1 筆 CREATE）
    await _svc.submit(db, doc_id=r.doc_id, version_id=r.version_id, assigned_reviewer="rev1", op=_op("ed"))
    creates = await db.scalar(
        text(
            'SELECT count(*) FROM "DP_AUDIT_LOG" WHERE "FUNC_NAME"=\'DM-EDITOR\' '
            'AND "ACTION_TYPE"=\'CREATE\' AND "TARGET_ID"=:d'
        ),
        {"d": r.doc_id},
    )
    updates = await db.scalar(
        text(
            'SELECT count(*) FROM "DP_AUDIT_LOG" WHERE "FUNC_NAME"=\'DM-EDITOR\' '
            'AND "ACTION_TYPE"=\'UPDATE\' AND "TARGET_ID"=:d'
        ),
        {"d": r.doc_id},
    )
    assert creates == 1 and updates == 1  # 新增 1 筆 CREATE、送簽 1 筆 UPDATE


async def test_get_options_returns_controlled_lists(db):
    await _make_func(db, "F010", "作業A")
    await _make_retrieval_tag(db, "平時", group="NATURE")
    opts = await _svc.get_options(db)
    cat_codes = {c.code for c in opts.categories}
    assert {"SOP", "MANUAL"} <= cat_codes
    assert any(f.code == "F010" for f in opts.funcs)
    assert any(a.name == "全體" for a in opts.audiences)  # 可見對象含全體
    assert any(t.name == "平時" and t.group_code == "NATURE" for t in opts.retrieval_tags)


# ── HTTP 存取閘 + multipart 落盤 ──────────────────────


async def test_http_create_requires_auth(db, client):
    resp = await client.post("/api/dm/documents", data={"doc_name": "x"})
    assert resp.status_code == 401


async def test_http_create_forbidden_without_editor_role(db, client):
    await _seed_user(db, "viewer1", "純閱覽")
    await _grant(db, "viewer1", DM_VIEWER)  # 有 DM 角色但非編輯者
    token = create_access_token(sub="viewer1", ttl_minutes=15)
    aud = await _audience_id(db, "全體")
    resp = await client.post(
        "/api/dm/documents",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "doc_name": "d",
            "category_code": "SOP",
            "version_no": "1.0",
            "change_summary": "s",
            "audience_ids": [aud],
        },
        files={"file": ("a.pdf", b"%PDF-1.4 x", _PDF)},
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"


async def test_http_create_multipart_success(db, client):
    await _seed_user(db, "editor1", "編輯者")
    await _grant(db, "editor1", DM_EDITOR)
    token = create_access_token(sub="editor1", ttl_minutes=15)
    aud = await _audience_id(db, "全體")
    resp = await client.post(
        "/api/dm/documents",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "doc_name": "領血SOP",
            "category_code": "SOP",
            "version_no": "1.0",
            "change_summary": "首版",
            "audience_ids": [aud],
        },
        files={"file": ("a.pdf", b"%PDF-1.4 realbytes", _PDF)},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["doc_id"] == "DM-SOP-000001" and body["previewable"] is True


async def test_http_add_version_requires_auth(db, client):
    resp = await client.post(
        "/api/dm/documents/DM-SOP-000001/versions",
        data={"version_no": "2.0", "change_summary": "x"},
        files={"file": ("a.pdf", b"%PDF-1.4 x", _PDF)},
    )
    assert resp.status_code == 401


async def test_http_add_version_forbidden_without_editor(db, client):
    await _seed_user(db, "viewer2", "純閱覽")
    await _grant(db, "viewer2", DM_VIEWER)
    token = create_access_token(sub="viewer2", ttl_minutes=15)
    resp = await client.post(
        "/api/dm/documents/DM-SOP-000001/versions",
        headers={"Authorization": f"Bearer {token}"},
        data={"version_no": "2.0", "change_summary": "x"},
        files={"file": ("a.pdf", b"%PDF-1.4 x", _PDF)},
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"


async def test_http_submit_requires_auth(db, client):
    resp = await client.post("/api/dm/documents/DM-SOP-000001/submit", json={"version_id": 1, "assigned_reviewer": "r"})
    assert resp.status_code == 401


async def test_http_submit_forbidden_without_editor(db, client):
    await _seed_user(db, "viewer3", "純閱覽")
    await _grant(db, "viewer3", DM_VIEWER)
    token = create_access_token(sub="viewer3", ttl_minutes=15)
    resp = await client.post(
        "/api/dm/documents/DM-SOP-000001/submit",
        headers={"Authorization": f"Bearer {token}"},
        json={"version_id": 1, "assigned_reviewer": "r"},
    )
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_002"
