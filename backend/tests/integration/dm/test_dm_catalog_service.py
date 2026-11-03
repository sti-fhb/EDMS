"""受控資料維護服務整合測試（T020，真實 DB）。

驗證：新增分類（重複碼擋）、改名、啟停（不刪除、既有引用保留）、AUDIENCE soft-retire 回傳受影響數。
"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.catalog.service import CatalogService
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion, DmVersionTag

pytestmark = pytest.mark.integration

_svc = CatalogService()


async def test_create_category_and_duplicate_rejected(db):
    """新增自訂分類（IS_BUILTIN=false）；重複碼 → 409 DM_CATALOG_001。"""
    cat = await _svc.create_category(db, code="ZTCUST", name="自訂類", operator="admin")
    assert cat.is_builtin is False and cat.is_enabled is True
    with pytest.raises(AppError) as e:
        await _svc.create_category(db, code="ZTCUST", name="重複", operator="admin")
    assert e.value.error_code == "DM_CATALOG_001"


async def test_rename_and_disable_keeps_code(db):
    """改名不動代碼；停用不刪除（既有列仍在，只是 is_enabled=false）。"""
    await _svc.create_category(db, code="ZTREN", name="舊名", operator="a")
    renamed = await _svc.rename_category(db, code="ZTREN", new_name="新名", operator="a")
    assert renamed.category_code == "ZTREN" and renamed.category_name == "新名"
    disabled = await _svc.set_category_enabled(db, code="ZTREN", enabled=False, operator="a")
    assert disabled.is_enabled is False and disabled.category_code == "ZTREN"


async def test_create_category_rejects_non_alnum_code(db):
    """分類碼含非英數字元（下游 next_doc_id 以此碼組 LIKE）→ 422 DM_CATALOG_003。"""
    for bad in ("ZT_X", "ZT%", "ZT-1", "類別"):
        with pytest.raises(AppError) as e:
            await _svc.create_category(db, code=bad, name="x", operator="a")
        assert e.value.error_code == "DM_CATALOG_003"


async def test_require_category_404(db):
    with pytest.raises(AppError) as e:
        await _svc.rename_category(db, code="NOPE", new_name="x", operator="a")
    assert e.value.error_code == "DM_CATALOG_002"


async def test_audience_soft_retire_排除已軟刪除之關聯(db):
    """受影響數須濾 `DELETED = 0`——標籤關聯採**軟刪除復用**（移除＝`deleted=1` 不刪列，
    見 `dm/editor/repository.py` 的 upsert），不濾會把「曾經掛過、後來被移除」的文件與
    已撤銷的閱覽者授權一併算進去，數字偏高。

    本數字自 #182 起是 DP03 停用可見對象時呈現給管理者的決策依據，高估會讓他誤判影響範圍；
    且與 `DM_VERSION_TAG` 未計的低估方向相反、互相掩蓋，使誤差方向不明。先修此項讓誤差
    收斂為單一方向（已知偏低），介面才能誠實標示「至少 N 份」。`DM_VERSION_TAG` 之低估待 #388。
    """
    now = utcnow()
    tag = DmTag(tag_group_code="AUDIENCE", tag_name="ZT受影響數", created_user="e", created_date=now)
    db.add(tag)
    await db.flush()
    for doc_id in ("DM-SOP-900001", "DM-SOP-900002"):
        db.add(
            DmDocument(
                doc_id=doc_id, doc_name="d", category_code="SOP", status="PUBLISHED", created_user="e", created_date=now
            )
        )
    await db.flush()
    # 一份有效、一份已移除（軟刪除列仍在）
    db.add(DmDocTag(doc_id="DM-SOP-900001", tag_id=tag.tag_id, created_user="e", created_date=now, deleted=0))
    db.add(DmDocTag(doc_id="DM-SOP-900002", tag_id=tag.tag_id, created_user="e", created_date=now, deleted=1))
    # 一位有效、一位已撤銷授權
    db.add(DmUserTag(user_id="ztv1", tag_id=tag.tag_id, created_user="admin", created_date=now, deleted=0))
    db.add(DmUserTag(user_id="ztv2", tag_id=tag.tag_id, created_user="admin", created_date=now, deleted=1))
    await db.flush()

    result = await _svc.soft_retire_audience_tag(db, tag_id=tag.tag_id, operator="admin")

    assert result.affected_docs == 1, "已移除之文件關聯不得計入"
    assert result.affected_viewers == 1, "已撤銷之閱覽者授權不得計入"


async def test_audience_soft_retire_returns_affected_counts(db):
    """停用可見對象 soft-retire：is_enabled=false + 回傳受影響文件 / 閱覽者數，既有列不收回。"""
    now = utcnow()
    tag = (
        await db.execute(select(DmTag).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == "護理師"))
    ).scalar_one()
    # 1 份文件掛此可見對象、2 位閱覽者被授予
    db.add(
        DmDocument(
            doc_id="DM-SOP-000001",
            doc_name="d",
            category_code="SOP",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()
    db.add(DmDocTag(doc_id="DM-SOP-000001", tag_id=tag.tag_id, created_user="e", created_date=now))
    db.add(DmUserTag(user_id="v1", tag_id=tag.tag_id, created_user="admin", created_date=now))
    db.add(DmUserTag(user_id="v2", tag_id=tag.tag_id, created_user="admin", created_date=now))
    await db.flush()

    result = await _svc.soft_retire_audience_tag(db, tag_id=tag.tag_id, operator="admin")
    assert result.affected_docs == 1 and result.affected_viewers == 2
    # soft-retire：標籤停用但既有 DOC_TAG / USER_TAG 保留（不收回可見性）
    refreshed = (await db.execute(select(DmTag).where(DmTag.tag_id == tag.tag_id))).scalar_one()
    assert refreshed.is_enabled is False
    assert (await db.scalar(select(DmDocTag.doc_tag_id).where(DmDocTag.tag_id == tag.tag_id))) is not None


# ─────────────────────────────────────────────────────────────────────────────
# L1-b：受影響數要計入在途草稿的版本層快照（#388）
# ─────────────────────────────────────────────────────────────────────────────


def _ztdoc(doc_id: str, now) -> DmDocument:
    return DmDocument(
        doc_id=doc_id, doc_name="d", category_code="SOP", status="PUBLISHED", created_user="e", created_date=now
    )


def _ztver(doc_id: str, status: str, now) -> DmDocVersion:
    return DmDocVersion(
        doc_id=doc_id, version_no="1.0", change_summary="c", status=status, created_user="e", created_date=now
    )


async def test_audience_soft_retire_計入在途草稿之版本層快照(db):
    """標籤自 #377 起於草稿階段只寫 `DM_VERSION_TAG`，核准發布時才套用至 `DM_DOC_TAG`。

    只數 `DM_DOC_TAG` 會漏掉所有尚未核准的設定——管理者看到的是「已經生效的那些」，
    而他要決定的是「停用後會發生什麼」，在途草稿正屬於後者（核准時會被濾掉，見 L1-a）。

    ⛔ 已發布版（`PUBLISHED`）的快照**不得計入**：它已經套用成 `DM_DOC_TAG` 列了，
    再數一次就是同一筆設定算兩次。
    """
    now = utcnow()
    tag = DmTag(tag_group_code="AUDIENCE", tag_name="ZT在途快照", created_user="e", created_date=now)
    db.add(tag)
    db.add_all([_ztdoc("DM-SOP-900011", now), _ztdoc("DM-SOP-900012", now)])
    await db.flush()

    published = _ztver("DM-SOP-900011", "PUBLISHED", now)
    draft = _ztver("DM-SOP-900011", "DRAFT", now)
    pending = _ztver("DM-SOP-900012", "PENDING_REVIEW", now)
    removed = _ztver("DM-SOP-900012", "DRAFT", now)
    db.add_all([published, draft, pending, removed])
    # 已生效 1 筆
    db.add(DmDocTag(doc_id="DM-SOP-900011", tag_id=tag.tag_id, created_user="e", created_date=now, deleted=0))
    await db.flush()
    db.add_all(
        [
            # 已發布版之快照：已套用成上面那筆 DM_DOC_TAG，不得再算一次
            DmVersionTag(version_id=published.version_id, tag_id=tag.tag_id, created_user="e", created_date=now),
            # 在途 2 筆
            DmVersionTag(version_id=draft.version_id, tag_id=tag.tag_id, created_user="e", created_date=now),
            DmVersionTag(version_id=pending.version_id, tag_id=tag.tag_id, created_user="e", created_date=now),
            # 草稿裡已被移除（軟刪除復用）
            DmVersionTag(
                version_id=removed.version_id, tag_id=tag.tag_id, created_user="e", created_date=now, deleted=1
            ),
        ]
    )
    await db.flush()

    result = await _svc.soft_retire_audience_tag(db, tag_id=tag.tag_id, operator="admin")

    assert result.affected_docs == 3, "應為 1 筆已生效 + 2 筆在途（已發布版快照與已移除者不計）"


async def test_audience_soft_retire_在途快照之單位那一半(db):
    """🔴 配對的兩半都要查。`UNIT_TAG_ID` 與 `TAG_ID` 同為 FK → `DM_TAG.TAG_ID`（#437）。

    在途快照若只比對 `TAG_ID`，停用單位時這段恆為 0——而恆為 0 的症狀與「真的沒有在途草稿」
    完全相同，管理者不會察覺少算。`DM_DOC_TAG` 那半已於 #182 守住，本條守版本層。
    """
    now = utcnow()
    unit = DmTag(tag_group_code="AUDIENCE", tag_name="ZT在途單位", created_user="e", created_date=now)
    role = DmTag(tag_group_code="AUDIENCE", tag_name="ZT在途職位", created_user="e", created_date=now)
    db.add_all([unit, role])
    db.add(_ztdoc("DM-SOP-900013", now))
    await db.flush()
    draft = _ztver("DM-SOP-900013", "DRAFT", now)
    db.add(draft)
    await db.flush()
    db.add(
        DmVersionTag(
            version_id=draft.version_id,
            tag_id=role.tag_id,
            unit_tag_id=unit.tag_id,
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()

    result = await _svc.soft_retire_audience_tag(db, tag_id=unit.tag_id, operator="admin", is_unit=True)

    assert result.affected_docs == 1, "停用單位時，在途快照須依 UNIT_TAG_ID 比對"
