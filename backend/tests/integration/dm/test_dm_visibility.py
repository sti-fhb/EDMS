"""標籤式可見性判定整合測試（T020a，真實 DB）。

驗證：閱覽者僅見「全體」或其可見對象授權相符之文件；編輯者 / 審核者 / 管理者不過濾（見全部）。
使用業務種子之 AUDIENCE 標籤（全體 / 護理師 / 軍人）。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmFunc, DmTag  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocTag, DmDocument
from app.dm.document.visibility import visible_docs_condition
from app.dm.roles.authz import DM_EDITOR, DM_VIEWER

pytestmark = pytest.mark.integration


async def _tag_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == tag_name))


async def _doc_with_audience(db, doc_id: str, audience_tag_name: str):
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id, doc_name=doc_id, category_code="SOP", status="PUBLISHED", created_user="e", created_date=now
        )
    )
    await db.flush()
    db.add(DmDocTag(doc_id=doc_id, tag_id=await _tag_id(db, audience_tag_name), created_user="e", created_date=now))
    await db.flush()


async def _visible_doc_ids(db, user_id: str, roles: set[str]) -> set[str]:
    cond = visible_docs_condition(user_id, roles)
    stmt = select(DmDocument.doc_id)
    if cond is not None:
        stmt = stmt.where(cond)
    return set((await db.execute(stmt)).scalars().all())


async def test_viewer_no_tags_sees_only_all(db):
    """無可見對象授權之閱覽者：僅見掛「全體」之文件。"""
    await _doc_with_audience(db, "DM-SOP-000001", "全體")
    await _doc_with_audience(db, "DM-SOP-000002", "護理師")
    visible = await _visible_doc_ids(db, "viewer_none", {DM_VIEWER})
    assert "DM-SOP-000001" in visible
    assert "DM-SOP-000002" not in visible


async def test_viewer_with_tag_sees_all_plus_matching(db):
    """具「護理師」授權之閱覽者：見「全體」+「護理師」文件，不見「軍人」文件。"""
    await _doc_with_audience(db, "DM-SOP-000001", "全體")
    await _doc_with_audience(db, "DM-SOP-000002", "護理師")
    await _doc_with_audience(db, "DM-SOP-000003", "軍人")
    db.add(
        DmUserTag(
            user_id="viewer_nurse", tag_id=await _tag_id(db, "護理師"), created_user="admin", created_date=utcnow()
        )
    )
    await db.flush()
    visible = await _visible_doc_ids(db, "viewer_nurse", {DM_VIEWER})
    assert {"DM-SOP-000001", "DM-SOP-000002"} <= visible
    assert "DM-SOP-000003" not in visible


async def test_editor_not_filtered(db):
    """編輯者：不套可見性過濾（見全部）——condition 回 None。"""
    await _doc_with_audience(db, "DM-SOP-000003", "軍人")
    assert visible_docs_condition("editor1", {DM_EDITOR}) is None
    visible = await _visible_doc_ids(db, "editor1", {DM_EDITOR})
    assert "DM-SOP-000003" in visible
