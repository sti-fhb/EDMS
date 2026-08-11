"""文件庫與檢索（US3 / DM01）整合測試（真實 DB）。

驗證：多條件搜尋、狀態集合（PUBLISHED + PENDING_OBSOLETE 目前版本、排除其餘）、標籤式可見性
（閱覽者過濾 / 其他角色不過濾）、系統操作手冊 func 唯一、檢索標籤下拉排除可見對象、排序分頁、
以及 HTTP 存取閘（無 DM 角色 403 / 未認證 401）。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmFunc, DmTag
from app.dm.deps import DmContext
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.library.schemas import DocumentQuery
from app.dm.library.service import LibraryService
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = LibraryService()


async def _audience_tag_id(db, name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _make_retrieval_tag(db, name: str) -> int:
    """於 NATURE（RETRIEVAL 組）建一檢索標籤，回 TAG_ID。"""
    tag = DmTag(tag_group_code="NATURE", tag_name=name, created_user="seed", created_date=utcnow())
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _make_func(db, code: str, name: str) -> None:
    db.add(DmFunc(func_code=code, func_name=name, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _seed_user(db, user_id: str, user_name: str) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@example.com",
            pwd_hash="x",
            user_name=user_name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _seed_doc(
    db,
    *,
    doc_id: str,
    name: str,
    category: str = "SOP",
    func_code: str | None = None,
    author: str = "u_author",
    status: str = "PUBLISHED",
    published_date=None,
    change_summary: str = "初版摘要",
    audience_tags=(),
    retrieval_tag_ids=(),
) -> None:
    """建立「目前版本」文件（版本 PUBLISHED + 文件層 status 可指定，供狀態集合測試）。

    DM_DOCUMENT 與 DM_DOC_VERSION 互為 FK（循環）：先插文件（current_version_id=None）→ 插版本 → 回填。
    """
    now = utcnow()
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=name,
        category_code=category,
        func_code=func_code,
        current_version_id=None,
        status=status,
        created_user=author,
        created_date=now,
    )
    db.add(doc)
    await db.flush()
    ver = DmDocVersion(
        doc_id=doc_id,
        version_no="1.0",
        change_summary=change_summary,
        file_name="f.pdf",
        file_path="/x/f.pdf",
        file_size=1,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=published_date or now,
        created_user=author,
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc.current_version_id = ver.version_id
    await db.flush()
    for tname in audience_tags:
        db.add(DmDocTag(doc_id=doc_id, tag_id=await _audience_tag_id(db, tname), created_user=author, created_date=now))
    for tid in retrieval_tag_ids:
        db.add(DmDocTag(doc_id=doc_id, tag_id=tid, created_user=author, created_date=now))
    await db.flush()


def _admin_ctx() -> DmContext:
    return DmContext(user_id="adm", roles=frozenset({DM_ADMIN}))


def _q(**kw) -> DocumentQuery:
    return DocumentQuery(**kw)


async def _ids(db, ctx=None, **query_kw) -> set[str]:
    res = await _svc.search(db, query=_q(**query_kw), ctx=ctx or _admin_ctx(), page=1, limit=20)
    return {i.doc_id for i in res["data"]}


# ── 狀態集合 ───────────────────────────────────────────────


async def test_only_published_and_pending_obsolete_current(db):
    """僅回 PUBLISHED + PENDING_OBSOLETE 之目前版本；DRAFT / PENDING_REVIEW / OBSOLETE 不出現。"""
    await _seed_doc(db, doc_id="DM-SOP-000001", name="已發布A", status="PUBLISHED")
    await _seed_doc(db, doc_id="DM-SOP-000002", name="廢止待簽核B", status="PENDING_OBSOLETE")
    await _seed_doc(db, doc_id="DM-SOP-000003", name="草稿C", status="DRAFT")
    await _seed_doc(db, doc_id="DM-SOP-000004", name="送審中D", status="PENDING_REVIEW")
    await _seed_doc(db, doc_id="DM-SOP-000005", name="已廢止E", status="OBSOLETE")
    ids = await _ids(db)
    assert {"DM-SOP-000001", "DM-SOP-000002"} <= ids
    assert not ({"DM-SOP-000003", "DM-SOP-000004", "DM-SOP-000005"} & ids)


# ── 多條件 ─────────────────────────────────────────────────


async def test_keyword_matches_name_or_change_summary(db):
    await _seed_doc(db, doc_id="DM-SOP-000010", name="領血確認程序", change_summary="無關")
    await _seed_doc(db, doc_id="DM-SOP-000011", name="其他文件", change_summary="含關鍵字血袋")
    await _seed_doc(db, doc_id="DM-SOP-000012", name="不相關", change_summary="不相關")
    assert await _ids(db, keyword="血") == {"DM-SOP-000010", "DM-SOP-000011"}


async def test_filter_by_category(db):
    await _seed_doc(db, doc_id="DM-SOP-000020", name="s", category="SOP")
    await _seed_doc(db, doc_id="DM-MANUAL-000021", name="m", category="MANUAL")
    assert await _ids(db, category="MANUAL") == {"DM-MANUAL-000021"}


async def test_filter_by_author_name(db):
    await _seed_user(db, "au_wang", "王曉明")
    await _seed_user(db, "au_chen", "陳大華")
    await _seed_doc(db, doc_id="DM-SOP-000030", name="a", author="au_wang")
    await _seed_doc(db, doc_id="DM-SOP-000031", name="b", author="au_chen")
    assert await _ids(db, author="王曉") == {"DM-SOP-000030"}


async def test_filter_by_retrieval_tags_and(db):
    """多檢索標籤 AND：僅同時掛兩標籤者命中。"""
    t_normal = await _make_retrieval_tag(db, "平時")
    t_war = await _make_retrieval_tag(db, "戰時")
    await _seed_doc(db, doc_id="DM-SOP-000040", name="both", retrieval_tag_ids=[t_normal, t_war])
    await _seed_doc(db, doc_id="DM-SOP-000041", name="one", retrieval_tag_ids=[t_normal])
    assert await _ids(db, tag_ids=[t_normal, t_war]) == {"DM-SOP-000040"}


async def test_filter_by_date_range(db):
    from datetime import datetime, timezone

    await _seed_doc(db, doc_id="DM-SOP-000050", name="old", published_date=datetime(2026, 1, 10, tzinfo=timezone.utc))
    await _seed_doc(db, doc_id="DM-SOP-000051", name="mid", published_date=datetime(2026, 3, 15, tzinfo=timezone.utc))
    await _seed_doc(db, doc_id="DM-SOP-000052", name="new", published_date=datetime(2026, 6, 20, tzinfo=timezone.utc))
    from datetime import date

    assert await _ids(db, date_from=date(2026, 3, 1), date_to=date(2026, 4, 1)) == {"DM-SOP-000051"}


# ── 可見性（核心）───────────────────────────────────────────


async def test_viewer_visibility_filters_by_audience(db):
    """閱覽者僅見「全體」或可見對象相符；編輯者不過濾（見全部）。"""
    await _seed_doc(db, doc_id="DM-SOP-000060", name="all", audience_tags=["全體"])
    await _seed_doc(db, doc_id="DM-SOP-000061", name="nurse", audience_tags=["護理師"])
    await _seed_doc(db, doc_id="DM-SOP-000062", name="army", audience_tags=["軍人"])
    nurse_tag = await _audience_tag_id(db, "護理師")
    db.add(DmUserTag(user_id="v_nurse", tag_id=nurse_tag, created_user="a", created_date=utcnow()))
    await db.flush()
    viewer = DmContext(user_id="v_nurse", roles=frozenset({DM_VIEWER}))
    vis = await _ids(db, ctx=viewer)
    assert {"DM-SOP-000060", "DM-SOP-000061"} <= vis and "DM-SOP-000062" not in vis
    # 編輯者不過濾
    editor = DmContext(user_id="v_nurse", roles=frozenset({DM_EDITOR}))
    assert {"DM-SOP-000060", "DM-SOP-000061", "DM-SOP-000062"} <= await _ids(db, ctx=editor)


async def test_viewer_no_audience_sees_only_all(db):
    await _seed_doc(db, doc_id="DM-SOP-000070", name="all", audience_tags=["全體"])
    await _seed_doc(db, doc_id="DM-SOP-000071", name="nurse", audience_tags=["護理師"])
    viewer = DmContext(user_id="v_none", roles=frozenset({DM_VIEWER}))
    assert await _ids(db, ctx=viewer) == {"DM-SOP-000070"}


async def test_pending_obsolete_visible_to_viewer(db):
    """廢止待簽核（PENDING_OBSOLETE）文件對閱覽者仍可見（狀態集合與可見性分開 AND）。"""
    await _seed_doc(db, doc_id="DM-SOP-000080", name="po", status="PENDING_OBSOLETE", audience_tags=["全體"])
    viewer = DmContext(user_id="v_any", roles=frozenset({DM_VIEWER}))
    assert "DM-SOP-000080" in await _ids(db, ctx=viewer)


# ── 手冊 func 檢索 / 排序分頁 / 空 ───────────────────────────


async def test_manual_func_filter_unique(db):
    await _make_func(db, "BS04", "領血確認")
    await _seed_doc(db, doc_id="DM-MANUAL-000090", name="BS04手冊", category="MANUAL", func_code="BS04")
    await _seed_doc(db, doc_id="DM-MANUAL-000091", name="其他手冊", category="MANUAL", func_code=None)
    assert await _ids(db, category="MANUAL", func_code="BS04") == {"DM-MANUAL-000090"}


async def test_sort_desc_and_pagination(db):
    from datetime import datetime, timezone

    for n in range(3):
        await _seed_doc(
            db,
            doc_id=f"DM-SOP-00010{n}",
            name=f"d{n}",
            published_date=datetime(2026, 1, 1 + n, tzinfo=timezone.utc),
        )
    res = await _svc.search(db, query=_q(), ctx=_admin_ctx(), page=1, limit=2)
    assert res["meta"]["total"] >= 3 and res["meta"]["limit"] == 2
    # 最新（day 3）排最前
    assert res["data"][0].doc_id == "DM-SOP-000102"


async def test_empty_result(db):
    res = await _svc.search(db, query=_q(keyword="絕不存在的字串xyz"), ctx=_admin_ctx(), page=1, limit=20)
    assert res["data"] == [] and res["meta"]["total"] == 0


# ── 受控清單下拉 ───────────────────────────────────────────


async def test_retrieval_tags_exclude_audience(db):
    """檢索標籤下拉僅列 RETRIEVAL 組，不含 AUDIENCE（可見對象）。"""
    await _make_retrieval_tag(db, "檢索用A")
    opts = await _svc.list_retrieval_tags(db)
    names = {o.name for o in opts}
    assert "檢索用A" in names
    assert "全體" not in names and "護理師" not in names  # AUDIENCE 不入下拉


async def test_list_item_shows_retrieval_tags_only(db):
    """清單標籤只呈現檢索標籤，不含可見對象標籤。"""
    t = await _make_retrieval_tag(db, "平時X")
    await _seed_doc(db, doc_id="DM-SOP-000110", name="doc", audience_tags=["全體"], retrieval_tag_ids=[t])
    res = await _svc.search(db, query=_q(keyword="doc"), ctx=_admin_ctx(), page=1, limit=20)
    item = next(i for i in res["data"] if i.doc_id == "DM-SOP-000110")
    assert item.tags == ["平時X"]  # 只檢索標籤，無「全體」


async def test_disabled_retrieval_tag_still_shown_on_existing_doc(db):
    """檢索標籤停用後：既有掛該標籤之文件清單**仍顯示**（FR-001 既有引用保留），但下拉不再列出。"""
    t = await _make_retrieval_tag(db, "將停用X")
    await _seed_doc(db, doc_id="DM-SOP-000120", name="doc-disabled-tag", retrieval_tag_ids=[t])
    tag = await db.scalar(select(DmTag).where(DmTag.tag_id == t))
    tag.is_enabled = False
    await db.flush()
    res = await _svc.search(db, query=_q(keyword="doc-disabled-tag"), ctx=_admin_ctx(), page=1, limit=20)
    item = next(i for i in res["data"] if i.doc_id == "DM-SOP-000120")
    assert item.tags == ["將停用X"]  # 既有標記仍顯示
    assert "將停用X" not in {o.name for o in await _svc.list_retrieval_tags(db)}  # 下拉不再列出


async def test_audience_tag_id_not_usable_as_search_filter(db):
    """直傳 AUDIENCE（可見對象）標籤 id 作 tag_ids 不生效（FR-009 僅檢索標籤可搜尋）→ 不匹配。"""
    await _seed_doc(db, doc_id="DM-SOP-000130", name="nurse-doc", audience_tags=["護理師"])
    nurse = await _audience_tag_id(db, "護理師")
    assert await _ids(db, tag_ids=[nurse]) == set()


# ── 操作能力（新增文件入口）───────────────────────────────


def test_capabilities_editor_can_create():
    """具編輯者角色 → can_create True；純閱覽者 → False（FR-006 / AC8）。"""
    assert _svc.capabilities(DmContext(user_id="e", roles=frozenset({DM_EDITOR}))).can_create is True
    assert _svc.capabilities(DmContext(user_id="v", roles=frozenset({DM_VIEWER}))).can_create is False


# ── HTTP 存取閘 ────────────────────────────────────────────


async def test_http_requires_auth(db, client):
    resp = await client.get("/api/dm/library/documents")
    assert resp.status_code == 401


async def test_http_forbidden_without_dm_role(db, client):
    """已認證但無任何 DM 角色 → 403（DM_AUTH_001，存取閘）。"""
    await _seed_user(db, "no_role", "無角色")
    token = create_access_token(sub="no_role", ttl_minutes=15)
    resp = await client.get("/api/dm/library/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_http_ok_with_dm_role(db, client):
    await _seed_user(db, "has_role", "有角色")
    db.add(DmUserRole(user_id="has_role", role_code=DM_VIEWER, created_user="a", created_date=utcnow()))
    await db.flush()
    token = create_access_token(sub="has_role", ttl_minutes=15)
    resp = await client.get("/api/dm/library/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and "data" in resp.json()
