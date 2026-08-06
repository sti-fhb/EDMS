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
from app.dm.document.models import DmDocTag, DmDocument

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
