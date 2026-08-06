"""DM 業務種子驗證（migration 種入之分類 / 標籤組 / 可見對象）。

apply_migrations 跑 upgrade head（含 dm_seed_business_data）後，種子資料應存在。
"""

import pytest
from sqlalchemy import func, select

from app.dm.catalog.models import DmCategory, DmTag, DmTagGroup

pytestmark = pytest.mark.integration


async def test_categories_seeded(db):
    """4 內建分類皆種入且 IS_BUILTIN=true、代碼含 MANUAL。"""
    rows = (await db.execute(select(DmCategory))).scalars().all()
    codes = {r.category_code for r in rows}
    assert {"SOP", "MANUAL", "TRAINING", "OTHER"} <= codes
    assert all(r.is_builtin for r in rows if r.category_code in {"SOP", "MANUAL", "TRAINING", "OTHER"})


async def test_tag_groups_seeded(db):
    """4 內建標籤組；AUDIENCE 組 GROUP_TYPE=AUDIENCE、其餘 RETRIEVAL。"""
    rows = {r.tag_group_code: r for r in (await db.execute(select(DmTagGroup))).scalars().all()}
    assert {"AUDIENCE", "MODULE", "NATURE", "LEGAL"} <= set(rows)
    assert rows["AUDIENCE"].group_type == "AUDIENCE"
    assert rows["MODULE"].group_type == "RETRIEVAL"


async def test_audience_tags_seeded(db):
    """AUDIENCE 組 5 個可見對象預設值（含通用值「全體」）。"""
    count = await db.scalar(select(func.count()).select_from(DmTag).where(DmTag.tag_group_code == "AUDIENCE"))
    assert count >= 5
    names = set((await db.execute(select(DmTag.tag_name).where(DmTag.tag_group_code == "AUDIENCE"))).scalars().all())
    assert {"全體", "護理師", "軍人", "醫檢師", "行政人員"} <= names
