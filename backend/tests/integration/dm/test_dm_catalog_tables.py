"""DM 受控資料表整合測試（DM_CATEGORY / DM_FUNC / DM_TAG_GROUP / DM_TAG，真實 DB）。

驗證 migration 建表 + 模型可寫讀 + 預設值 + DM_TAG → DM_TAG_GROUP 外鍵。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup

pytestmark = pytest.mark.integration


async def test_category_insert_with_defaults(db):
    """分類寫入；IS_BUILTIN 預設 false、IS_ENABLED 預設 true。"""
    db.add(DmCategory(category_code="SOP", category_name="標準作業程序", created_user="seed", created_date=utcnow()))
    await db.flush()
    row = (await db.execute(select(DmCategory).where(DmCategory.category_code == "SOP"))).scalar_one()
    assert row.category_name == "標準作業程序"
    assert row.is_builtin is False and row.is_enabled is True


async def test_func_insert(db):
    """func_name 受控清單寫入。"""
    db.add(DmFunc(func_code="BS04", func_name="領血確認", created_user="seed", created_date=utcnow()))
    await db.flush()
    assert (await db.execute(select(DmFunc).where(DmFunc.func_code == "BS04"))).scalar_one().func_name == "領血確認"


async def test_tag_group_and_tag_fk(db):
    """標籤組（AUDIENCE）+ 標籤，且 DM_TAG.TAG_GROUP_CODE 外鍵指向 DM_TAG_GROUP。"""
    now = utcnow()
    db.add(
        DmTagGroup(
            tag_group_code="AUDIENCE",
            tag_group_name="可見對象/單位",
            group_type="AUDIENCE",
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()
    db.add(DmTag(tag_group_code="AUDIENCE", tag_name="全體", created_user="seed", created_date=now))
    await db.flush()
    tag = (await db.execute(select(DmTag).where(DmTag.tag_name == "全體"))).scalar_one()
    assert tag.tag_group_code == "AUDIENCE" and tag.is_enabled is True and tag.tag_id is not None


async def test_tag_bad_group_fk_rejected(db):
    """DM_TAG 指向不存在之標籤組 → 外鍵擋下。"""
    db.add(DmTag(tag_group_code="NOPE", tag_name="孤兒", created_user="seed", created_date=utcnow()))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_tag_group_type_default_retrieval(db):
    """標籤組 GROUP_TYPE 預設 RETRIEVAL。"""
    db.add(DmTagGroup(tag_group_code="NATURE", tag_group_name="文件性質", created_user="seed", created_date=utcnow()))
    await db.flush()
    row = (await db.execute(select(DmTagGroup).where(DmTagGroup.tag_group_code == "NATURE"))).scalar_one()
    assert row.group_type == "RETRIEVAL" and row.is_builtin is True
