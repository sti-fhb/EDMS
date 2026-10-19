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
from app.dm.catalog.models import DmCategory, DmFunc, DmTag
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
    """取 NATURE（RETRIEVAL 組）之檢索標籤，回 TAG_ID；seed 已有同名者沿用。

    `DM_TAG` 組內名稱唯一（`UQ_DM_TAG_GROUP_NAME`，#437），重建同名會撞唯一鍵。
    """
    existing = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "NATURE", DmTag.tag_name == name))
    if existing is not None:
        return existing
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
    version_author: str | None = None,
    status: str = "PUBLISHED",
    published_date=None,
    change_summary: str = "初版摘要",
    audience_tags=(),
    retrieval_tag_ids=(),
) -> None:
    """建立「目前版本」文件（版本 PUBLISHED + 文件層 status 可指定，供狀態集合測試）。

    DM_DOCUMENT 與 DM_DOC_VERSION 互為 FK（循環）：先插文件（current_version_id=None）→ 插版本 → 回填。

    `author` 寫入 `DM_DOCUMENT.CREATED_USER`（文件建立者），`version_author` 寫入
    `DM_DOC_VERSION.CREATED_USER`（該版上傳者）；**不給就同值**。

    ⚠️ 預設同值是刻意的——既有測試不在乎兩者的差別。但也因此，**只用預設值的測試無法分辨
    「作者＝文件建立者」與「作者＝發布版上傳者」兩種定義**（#737 的病徵正是如此：
    `test_filter_by_author_name` 在改版前後都通過）。要驗作者定義的測試**必須**明確給
    `version_author`，否則它驗不到自己宣稱的事。
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
        created_user=version_author or author,
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc.current_version_id = ver.version_id
    await db.flush()
    # 可見對象為 (單位, 職位) 配對；單位一律「全單位」＝不限單位（#437）。檢索標籤無單位維度。
    all_units_id = await db.scalar(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == "全單位")
    )
    for tname in audience_tags:
        db.add(
            DmDocTag(
                doc_id=doc_id,
                tag_id=await _audience_tag_id(db, tname),
                unit_tag_id=all_units_id,
                created_user=author,
                created_date=now,
            )
        )
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


async def _search(db, ctx=None, **query_kw):
    """完整結果（含 `meta`）。驗作者搜尋時要連 `meta.total` 一起看——理由見下方 #737 那組測試。"""
    return await _svc.search(db, query=_q(**query_kw), ctx=ctx or _admin_ctx(), page=1, limit=20)


async def _add_version(db, *, doc_id: str, author: str, status: str, version_no: str) -> None:
    """為既有文件補一個**非目前版本**的版本列（不回填 `current_version_id`）。"""
    db.add(
        DmDocVersion(
            doc_id=doc_id,
            version_no=version_no,
            change_summary="新版摘要",
            file_name="f.pdf",
            file_path="/x/f.pdf",
            file_size=1,
            file_mime="application/pdf",
            status=status,
            published_date=None,
            created_user=author,
            created_date=utcnow(),
        )
    )
    await db.flush()


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


# ── 作者＝目前發布版本的上傳者（#737）──────────────────────
#
# 上面那條 `test_filter_by_author_name` **不足以**守這件事：它沒給 `version_author`，
# 文件建立者與版本上傳者同值，所以「作者取哪一個」改來改去它都會過。下面三條一律明確
# 讓兩者相異。對齊對象：DM03（`obsolete_archive/repository.py`）與 DM07（`detail/repository.py`）
# 早就取版本層上傳者，DM01 是唯一的例外。


async def test_作者取目前發布版上傳者_而非文件建立者(db):
    """甲建立文件、乙上傳目前發布版 ⇒ DM01 清單的作者顯示乙。"""
    await _seed_user(db, "au_jia", "柯建立")
    await _seed_user(db, "au_yi", "羅上傳")
    await _seed_doc(db, doc_id="DM-SOP-000730", name="跨人改版文件", author="au_jia", version_author="au_yi")

    [item] = (await _search(db, keyword="跨人改版文件"))["data"]

    assert item.author_id == "au_yi"
    assert item.author_name == "羅上傳"


async def test_作者搜尋比對發布版上傳者_含_total(db):
    """以上傳者查得到、以建立者查不到。

    ⚠️ `meta.total` 來自 `count_documents`，它有**自己的** `DpUser` join。只改
    `list_documents` 而漏改 `count_documents` 時，清單看起來正確、`total` 卻對不上
    ——這行 `total` 斷言就是守那一個，不是湊數。
    """
    await _seed_user(db, "au_jia2", "柯建立")
    await _seed_user(db, "au_yi2", "羅上傳")
    await _seed_doc(db, doc_id="DM-SOP-000731", name="y", author="au_jia2", version_author="au_yi2")

    hit = await _search(db, author="羅上傳")
    assert {i.doc_id for i in hit["data"]} == {"DM-SOP-000731"}
    assert hit["meta"]["total"] == 1

    # 反向：以**文件建立者**的姓名搜尋查不到。上面那組命中即證明搜尋本身有效，
    # 故這裡的 0 是「真的沒比對建立者」，不是「搜尋整個壞掉」。
    miss = await _search(db, author="柯建立")
    assert miss["meta"]["total"] == 0


async def test_送審中的新版不改變作者(db):
    """新版送審期間（未核准、非目前版本）⇒ 作者仍為目前發布版的上傳者。

    **三個人刻意都不同**：文件建立者 / 目前發布版上傳者 / 送審中新版上傳者。初版只讓後兩者
    不同，結果這條在**修改前就通過**（作者取建立者，而建立者剛好被我設成發布者）——
    它當時分辨不出任何東西。三者相異後，三種錯法各自對應一個不同的人名：

    | 實作 | `author_id` |
    |---|---|
    | 舊的（取文件建立者）| `au_jia3` ← 本條因此會紅 |
    | ✅ 正確（取目前發布版上傳者）| `au_pub` |
    | 誤改成「取最新版本」| `au_rev` ← 本條因此會紅 |
    """
    await _seed_user(db, "au_jia3", "柯建立")
    await _seed_user(db, "au_pub", "柯發布")
    await _seed_user(db, "au_rev", "羅送審")
    await _seed_doc(db, doc_id="DM-SOP-000732", name="審中文件", author="au_jia3", version_author="au_pub")
    await _add_version(db, doc_id="DM-SOP-000732", author="au_rev", status="PENDING_REVIEW", version_no="2.0")

    [item] = (await _search(db, keyword="審中文件"))["data"]
    assert item.author_id == "au_pub"

    assert await _ids(db, author="柯發布") == {"DM-SOP-000732"}  # 正向錨點：搜尋確實找得到這份
    assert await _ids(db, author="羅送審") == set()


async def test_上傳者查無_DP_USER_時只缺姓名(db):
    """`DP_USER` 查無對應列（`outerjoin` 未命中）⇒ `author_name` 為 None、`author_id` 仍在。

    `author_id` 不可能是 None（`BaseModel.CREATED_USER` 為 `nullable=False`），所以本條同時
    釘住「不要把 `outerjoin` 改成 `join`」——改了的話這份文件會**整個消失**，而不是只少一個姓名。
    """
    await _seed_doc(db, doc_id="DM-SOP-000735", name="無主文件", author="au_ghost", version_author="au_ghost")

    [item] = (await _search(db, keyword="無主文件"))["data"]

    assert item.author_id == "au_ghost"  # 沒有對應的 DP_USER 列，但 id 仍要在
    assert item.author_name is None


async def test_閱覽者的作者搜尋仍受可見性限制(db):
    """同一位上傳者的兩份文件，閱覽者只搜得到自己可見的那份。

    守的是「可見性條件與作者條件各自獨立 AND」。若日後有人把可見性併進 `DpUser` 的 join
    條件（或反過來），作者搜尋就會變成「這份文件存在嗎」的 oracle。security review 指出
    **目前沒有任何測試釘住這件事**，而它正是那種改動唯一會變紅的地方。

    ⭐ 單一斷言同時含正反兩面：可見的那份**要**出現、不可見的那份**不可**出現。只寫
    「搜不到」的話，搜尋整個壞掉時這條也會通過。
    """
    await _seed_user(db, "au_up", "羅上傳")
    await _seed_doc(db, doc_id="DM-SOP-000733", name="限護理師", version_author="au_up", audience_tags=["護理師"])
    await _seed_doc(db, doc_id="DM-SOP-000734", name="給全體", version_author="au_up", audience_tags=["全體"])
    viewer = DmContext(user_id="v_no_tag", roles=frozenset({DM_VIEWER}))

    assert await _ids(db, ctx=viewer, author="羅上傳") == {"DM-SOP-000734"}


async def test_filter_by_retrieval_tags_or(db):
    """多檢索標籤 OR：命中任一標籤即列出（spec_us3 FR-001）；無任一標籤者不列。"""
    t_normal = await _make_retrieval_tag(db, "平時")
    t_war = await _make_retrieval_tag(db, "戰時")
    await _seed_doc(db, doc_id="DM-SOP-000040", name="both", retrieval_tag_ids=[t_normal, t_war])
    await _seed_doc(db, doc_id="DM-SOP-000041", name="normal-only", retrieval_tag_ids=[t_normal])
    await _seed_doc(db, doc_id="DM-SOP-000043", name="war-only", retrieval_tag_ids=[t_war])
    await _seed_doc(db, doc_id="DM-SOP-000042", name="none", retrieval_tag_ids=[])
    ids = await _ids(db, tag_ids=[t_normal, t_war])
    assert ids == {"DM-SOP-000040", "DM-SOP-000041", "DM-SOP-000043"}  # 任一命中；無標籤者不列
    assert await _ids(db, tag_ids=[t_war]) == {"DM-SOP-000040", "DM-SOP-000043"}  # 單標籤：掛戰時者


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


async def test_revoked_audience_grant_not_visible(db):
    """撤銷（DELETED=1）之可見對象授權不再賦予可見性——閱覽者僅有軍人（護理師已撤）→ 看不到護理師文件。"""
    await _seed_doc(db, doc_id="DM-SOP-000140", name="nurse-doc", audience_tags=["護理師"])
    army = await _audience_tag_id(db, "軍人")
    nurse = await _audience_tag_id(db, "護理師")
    db.add(DmUserTag(user_id="v_rev", tag_id=army, created_user="a", created_date=utcnow()))  # 有效：軍人
    db.add(DmUserTag(user_id="v_rev", tag_id=nurse, created_user="a", created_date=utcnow(), deleted=1))  # 撤銷：護理師
    await db.flush()
    viewer = DmContext(user_id="v_rev", roles=frozenset({DM_VIEWER}))
    assert "DM-SOP-000140" not in await _ids(db, ctx=viewer)  # 護理師授權已撤 → 看不到


async def test_pending_obsolete_visible_to_viewer(db):
    """廢止待簽核（PENDING_OBSOLETE）文件對閱覽者仍可見（狀態集合與可見性分開 AND）。"""
    await _seed_doc(db, doc_id="DM-SOP-000080", name="po", status="PENDING_OBSOLETE", audience_tags=["全體"])
    viewer = DmContext(user_id="v_any", roles=frozenset({DM_VIEWER}))
    assert "DM-SOP-000080" in await _ids(db, ctx=viewer)


# ── 手冊 func 檢索 / 排序分頁 / 空 ───────────────────────────


async def test_manual_func_filter_unique(db):
    # ZT 前綴為測試專用代碼（主系統無此模組），避免與業務種子的真實代碼撞 PK
    await _make_func(db, "ZT04", "測試作業項目")
    await _seed_doc(db, doc_id="DM-MANUAL-000090", name="ZT04手冊", category="MANUAL", func_code="ZT04")
    await _seed_doc(db, doc_id="DM-MANUAL-000091", name="其他手冊", category="MANUAL", func_code=None)
    assert await _ids(db, category="MANUAL", func_code="ZT04") == {"DM-MANUAL-000090"}


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


async def test_category_options_includes_admin_added_category(db):
    """分類下拉取自 `DM_CATEGORY`，故管理者於 DP 後台新增的分類也會出現（#483 第 1 項）。

    此前三個查詢頁（DM01 / DM03 / DM06）的下拉是前端寫死的 4 筆，新增分類後可用它建文件
    卻篩不到——本條釘住「下拉來源是資料表而非常數」。
    """
    db.add(DmCategory(category_code="ZTNEW", category_name="測試新增分類", created_user="seed", created_date=utcnow()))
    await db.flush()

    opts = await _svc.list_category_options(db)

    by_code = {o.code: o.name for o in opts}
    assert by_code["ZTNEW"] == "測試新增分類"
    assert {"SOP", "MANUAL", "TRAINING", "OTHER"} <= by_code.keys()  # 4 內建仍在
    assert by_code["SOP"] == "標準作業程序"  # 名稱取自 DB，非前端常數的「SOP（標準作業程序）」


async def test_category_options_exclude_disabled(db):
    """停用的分類不入下拉（與 func / 檢索標籤一致：停用只影響後續搜尋，不動既有標記）。"""
    category = await db.scalar(select(DmCategory).where(DmCategory.category_code == "OTHER"))
    category.is_enabled = False
    await db.flush()

    assert "OTHER" not in {o.code for o in await _svc.list_category_options(db)}


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
