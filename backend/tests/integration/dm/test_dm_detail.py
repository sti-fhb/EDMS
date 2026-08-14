"""文件詳細頁瀏覽（US4 / DM02）整合測試（真實 DB）。

驗證：詳細（標題/資訊面板）、存取控制（閱覽者未授權擋、編輯者見全部）、檔案存取（PDF 預覽/下載、
Office 僅下載、舊版擋下載）、下載寫 DM_DOC_READ + 去重 + 預覽不寫、版本歷程、can_edit（PENDING 失效）、
廢止 read-only 資訊；另 HTTP 驗存取閘與 FileResponse。
"""

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.deps import DmContext
from app.dm.detail.service import DetailService
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = DetailService()


async def _seed_user(db, user_id, user_name):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=user_name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _audience_tag_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _make_retrieval_tag(db, name):
    t = DmTag(tag_group_code="NATURE", tag_name=name, created_user="seed", created_date=utcnow())
    db.add(t)
    await db.flush()
    return t.tag_id


async def _add_version(
    db,
    doc_id,
    version_no,
    *,
    mime="application/pdf",
    path="/x/a.pdf",
    approver="appr",
    author="u_author",
    summary="摘要",
    published=None,
    status="PUBLISHED",
):
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary=summary,
        file_name=f"{version_no}.pdf",
        file_path=path,
        file_size=100,
        file_mime=mime,
        status=status,
        approver_user_id=approver,
        published_date=published or utcnow(),
        created_user=author,
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    return v.version_id


async def _seed_doc(
    db,
    *,
    doc_id,
    name="doc",
    category="SOP",
    func_code=None,
    author="u_author",
    status="PUBLISHED",
    audience_tags=(),
    retrieval_tag_ids=(),
):
    """建文件（current null）→ 加一版 → 回填 current_version_id；回 current version_id。"""
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=name,
        category_code=category,
        func_code=func_code,
        current_version_id=None,
        status=status,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    vid = await _add_version(db, doc_id, "1.0", author=author)
    doc.current_version_id = vid
    await db.flush()
    for tn in audience_tags:
        db.add(
            DmDocTag(doc_id=doc_id, tag_id=await _audience_tag_id(db, tn), created_user=author, created_date=utcnow())
        )
    for tid in retrieval_tag_ids:
        db.add(DmDocTag(doc_id=doc_id, tag_id=tid, created_user=author, created_date=utcnow()))
    await db.flush()
    return doc, vid


async def _add_review(
    db,
    doc_id,
    *,
    review_type,
    status,
    reviewer="rev",
    applicant="u_author",
    approver=None,
    reason=None,
    obsolete_file=None,
):
    r = DmReview(
        doc_id=doc_id,
        review_type=review_type,
        assigned_reviewer=reviewer,
        status=status,
        submit_date=utcnow(),
        complete_date=utcnow() if status != "PENDING" else None,
        approver_user_id=approver,
        reason=reason,
        obsolete_file_name=obsolete_file,
        created_user=applicant,
        created_date=utcnow(),
    )
    db.add(r)
    await db.flush()


def _admin():
    return DmContext(user_id="adm", roles=frozenset({DM_ADMIN}))


def _editor(uid="ed"):
    return DmContext(user_id=uid, roles=frozenset({DM_EDITOR}))


# ── 詳細 + 資訊面板 ────────────────────────────────


async def test_detail_fields(db):
    await _seed_user(db, "u_author", "陳大華")
    await _seed_user(db, "appr", "李主任")
    t = await _make_retrieval_tag(db, "平時")
    await _seed_doc(db, doc_id="DM-SOP-000001", name="領血SOP", retrieval_tag_ids=[t])
    d = await _svc.get_detail(db, doc_id="DM-SOP-000001", ctx=_admin())
    assert d.doc_name == "領血SOP" and d.status == "PUBLISHED" and d.current_version_no == "1.0"
    assert d.author_name == "陳大華" and d.approver_name == "李主任"
    assert d.tags == ["平時"] and d.file is not None and d.file.previewable is True


# ── 存取控制 ──────────────────────────────────────


async def test_viewer_unauthorized_blocked(db):
    await _seed_doc(db, doc_id="DM-SOP-000010", audience_tags=["護理師"])
    viewer = DmContext(user_id="v_none", roles=frozenset({DM_VIEWER}))
    with pytest.raises(AppError) as e:
        await _svc.get_detail(db, doc_id="DM-SOP-000010", ctx=viewer)
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


async def test_editor_sees_any(db):
    await _seed_doc(db, doc_id="DM-SOP-000011", audience_tags=["護理師"])
    d = await _svc.get_detail(db, doc_id="DM-SOP-000011", ctx=_editor())
    assert d.doc_id == "DM-SOP-000011"


@pytest.mark.parametrize("doc_status", ["DRAFT", "PENDING_REVIEW"])
async def test_unpublished_doc_not_browsable_any_role(db, doc_status):
    """未發布文件（草稿 / 送審中）不在 DM02 瀏覽——不分角色（閱覽者 / 編輯者 / 管理者）皆 404。

    草稿 / 送審中屬作者個人專區（US9）/ 審核者簽核中心（US6），不由詳細頁呈現。
    """
    doc_id = f"DM-SOP-0001{'2' if doc_status == 'DRAFT' else '3'}"
    _, vid = await _seed_doc(db, doc_id=doc_id, status=doc_status, audience_tags=["全體"])
    viewer = DmContext(user_id="v_all", roles=frozenset({DM_VIEWER}))
    for ctx in (viewer, _editor(), _admin()):
        with pytest.raises(AppError) as e:
            await _svc.get_detail(db, doc_id=doc_id, ctx=ctx)
        assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"
    # 版本 / 檔案端點同樣擋
    with pytest.raises(AppError):
        await _svc.list_versions(db, doc_id=doc_id, ctx=_admin())
    with pytest.raises(AppError):
        await _svc.prepare_file(db, doc_id=doc_id, version_id=vid, disposition="preview", ctx=_admin())


async def test_inflight_version_never_in_history_any_role(db):
    """進行中新版本（PENDING_REVIEW）不列入版本歷程、亦不供取檔——不分角色（版本歷程僅歷來發布版）。"""
    _, cur = await _seed_doc(db, doc_id="DM-SOP-000014", audience_tags=["全體"])
    pending = await _add_version(db, "DM-SOP-000014", "2.0-draft", status="PENDING_REVIEW")
    viewer = DmContext(user_id="v_all", roles=frozenset({DM_VIEWER}))
    for ctx in (viewer, _editor(), _admin()):
        vers = await _svc.list_versions(db, doc_id="DM-SOP-000014", ctx=ctx)
        assert {v.version_id for v in vers} == {cur}  # 僅目前發布版，無進行中版本
        with pytest.raises(AppError) as e:
            await _svc.prepare_file(db, doc_id="DM-SOP-000014", version_id=pending, disposition="preview", ctx=ctx)
        assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


# ── 檔案存取 + 閱讀記錄 ────────────────────────────


async def _read_count(db, doc_id, version_id, user_id):
    return await db.scalar(
        select(func.count())
        .select_from(DmDocRead)
        .where(DmDocRead.doc_id == doc_id, DmDocRead.version_id == version_id, DmDocRead.created_user == user_id)
    )


async def test_download_current_writes_read_and_dedup(db):
    _, vid = await _seed_doc(db, doc_id="DM-SOP-000020")
    ctx = _editor("reader1")
    f = await _svc.prepare_file(db, doc_id="DM-SOP-000020", version_id=vid, disposition="download", ctx=ctx)
    assert f.inline is False
    assert await _read_count(db, "DM-SOP-000020", vid, "reader1") == 1
    # 再下載同版 → 去重、不增筆
    await _svc.prepare_file(db, doc_id="DM-SOP-000020", version_id=vid, disposition="download", ctx=ctx)
    assert await _read_count(db, "DM-SOP-000020", vid, "reader1") == 1


async def test_preview_does_not_write_read(db):
    _, vid = await _seed_doc(db, doc_id="DM-SOP-000021")
    ctx = _editor("reader2")
    f = await _svc.prepare_file(db, doc_id="DM-SOP-000021", version_id=vid, disposition="preview", ctx=ctx)
    assert f.inline is True
    assert await _read_count(db, "DM-SOP-000021", vid, "reader2") == 0


async def test_old_version_download_blocked(db):
    doc, cur = await _seed_doc(db, doc_id="DM-SOP-000022")
    old = await _add_version(db, "DM-SOP-000022", "0.9")  # 非目前版
    with pytest.raises(AppError) as e:
        await _svc.prepare_file(db, doc_id="DM-SOP-000022", version_id=old, disposition="download", ctx=_admin())
    assert e.value.status_code == 403 and e.value.error_code == "DM_DOC_002"
    # 舊版可預覽
    f = await _svc.prepare_file(db, doc_id="DM-SOP-000022", version_id=old, disposition="preview", ctx=_admin())
    assert f.inline is True


async def test_office_preview_blocked_download_ok(db):
    doc = DmDocument(
        doc_id="DM-SOP-000023",
        doc_name="d",
        category_code="SOP",
        current_version_id=None,
        status="PUBLISHED",
        created_user="u_author",
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    vid = await _add_version(
        db, "DM-SOP-000023", "1.0", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    doc.current_version_id = vid
    await db.flush()
    with pytest.raises(AppError) as e:
        await _svc.prepare_file(db, doc_id="DM-SOP-000023", version_id=vid, disposition="preview", ctx=_admin())
    assert e.value.status_code == 422 and e.value.error_code == "DM_DOC_003"
    # Office 目前版可下載
    f = await _svc.prepare_file(db, doc_id="DM-SOP-000023", version_id=vid, disposition="download", ctx=_admin())
    assert f.inline is False


# ── 版本歷程 ──────────────────────────────────────


async def test_versions_list_marks_current(db):
    doc, cur = await _seed_doc(db, doc_id="DM-SOP-000030")
    old = await _add_version(db, "DM-SOP-000030", "0.9")
    vers = await _svc.list_versions(db, doc_id="DM-SOP-000030", ctx=_admin())
    by_id = {v.version_id: v for v in vers}
    assert by_id[cur].is_current is True and by_id[old].is_current is False
    assert len(vers) == 2


# ── can_edit（PENDING 失效）────────────────────────


async def test_can_edit_editor_no_pending(db):
    await _seed_doc(db, doc_id="DM-SOP-000040")
    d = await _svc.get_detail(db, doc_id="DM-SOP-000040", ctx=_editor())
    assert d.is_editor is True and d.can_edit is True and d.edit_lock_reason is None
    # 非編輯者（管理者）→ 無編輯入口、不可點
    a = await _svc.get_detail(db, doc_id="DM-SOP-000040", ctx=_admin())
    assert a.is_editor is False and a.can_edit is False


async def test_can_edit_false_when_pending_review(db):
    """新版本送審中：編輯者仍為 is_editor，但入口失效並帶送審中原因（供前端灰階提示）。"""
    await _seed_doc(db, doc_id="DM-SOP-000041")
    await _add_review(db, "DM-SOP-000041", review_type="NEW_VERSION", status="PENDING")
    d = await _svc.get_detail(db, doc_id="DM-SOP-000041", ctx=_editor())
    assert d.is_editor is True and d.can_edit is False
    assert d.edit_lock_reason is not None and "送審中" in d.edit_lock_reason


async def test_edit_lock_reason_pending_obsolete(db):
    """廢止待簽核：入口失效原因標示為廢止待簽核（非送審中）。"""
    await _seed_doc(db, doc_id="DM-SOP-000042", status="PENDING_OBSOLETE")
    await _add_review(db, "DM-SOP-000042", review_type="OBSOLETE", status="PENDING")
    d = await _svc.get_detail(db, doc_id="DM-SOP-000042", ctx=_editor())
    assert d.can_edit is False and d.edit_lock_reason is not None and "廢止待簽核" in d.edit_lock_reason


# ── 廢止 read-only 資訊 ────────────────────────────


async def test_obsolete_info_banner(db):
    await _seed_user(db, "applicant1", "王曉明")
    await _seed_user(db, "approver1", "李主任")
    await _seed_doc(db, doc_id="DM-SOP-000050", status="OBSOLETE")
    await _add_review(
        db,
        "DM-SOP-000050",
        review_type="OBSOLETE",
        status="APPROVED",
        applicant="applicant1",
        approver="approver1",
        reason="院內停用",
        obsolete_file="函文.pdf",
    )
    d = await _svc.get_detail(db, doc_id="DM-SOP-000050", ctx=_admin())
    assert d.is_obsolete is True and d.obsolete_info is not None
    assert d.obsolete_info.applicant_name == "王曉明" and d.obsolete_info.approver_name == "李主任"
    assert d.obsolete_info.reason == "院內停用" and d.obsolete_info.has_attachment is True


# ── HTTP 存取閘 + FileResponse ─────────────────────


async def test_http_requires_auth(db, client):
    resp = await client.get("/api/dm/documents/DM-SOP-000001")
    assert resp.status_code == 401


async def test_http_forbidden_without_dm_role(db, client):
    await _seed_user(db, "no_role", "無角色")
    token = create_access_token(sub="no_role", ttl_minutes=15)
    resp = await client.get("/api/dm/documents/DM-SOP-000001", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_http_file_download_serves(db, client, tmp_path):
    """FileResponse 實際串流：目前版下載 → 200 + attachment。"""
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    doc = DmDocument(
        doc_id="DM-SOP-000060",
        doc_name="d",
        category_code="SOP",
        current_version_id=None,
        status="PUBLISHED",
        created_user="u_author",
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    vid = await _add_version(db, "DM-SOP-000060", "1.0", path=str(f))
    doc.current_version_id = vid
    await db.flush()
    await _seed_user(db, "has_role", "有角色")
    db.add(DmUserRole(user_id="has_role", role_code=DM_EDITOR, created_user="a", created_date=utcnow()))
    await db.flush()
    token = create_access_token(sub="has_role", ttl_minutes=15)
    resp = await client.get(
        f"/api/dm/documents/DM-SOP-000060/versions/{vid}/file?disposition=download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200 and resp.content == b"%PDF-1.4 test"
    assert "attachment" in resp.headers.get("content-disposition", "")


async def test_http_missing_physical_file_returns_404_not_500(db, client):
    """DB 有版本 metadata 但實體檔缺失：回 404 DM_DOC_001，非 500，且不洩露落盤路徑。"""
    secret_path = "/nonexistent/secret/vault/a.pdf"
    doc = DmDocument(
        doc_id="DM-SOP-000061",
        doc_name="d",
        category_code="SOP",
        current_version_id=None,
        status="PUBLISHED",
        created_user="u_author",
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    vid = await _add_version(db, "DM-SOP-000061", "1.0", path=secret_path)
    doc.current_version_id = vid
    await db.flush()
    await _seed_user(db, "role2", "有角色2")
    db.add(DmUserRole(user_id="role2", role_code=DM_EDITOR, created_user="a", created_date=utcnow()))
    await db.flush()
    token = create_access_token(sub="role2", ttl_minutes=15)
    resp = await client.get(
        f"/api/dm/documents/DM-SOP-000061/versions/{vid}/file?disposition=preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "DM_DOC_001"
    assert "secret" not in resp.text  # 落盤路徑不外洩
