"""DOC_ID next_doc_id 整合測試（真實 DB）：分類獨立流水、遞增、首號。"""

import pytest

from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc  # noqa: F401  # 註冊 DM_DOCUMENT 之 FK 目標表
from app.dm.document.docid import next_doc_id
from app.dm.document.models import DmDocument

pytestmark = pytest.mark.integration


async def _add_doc(db, doc_id: str, category_code: str):
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name="d",
            category_code=category_code,
            status="DRAFT",
            created_user="e",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def test_next_doc_id_first_is_000001(db):
    """該分類尚無文件 → 首號 000001（SOP 分類已由種子建立，可作 FK）。"""
    assert await next_doc_id(db, "SOP") == "DM-SOP-000001"


async def test_next_doc_id_increments(db):
    """有既有文件 → 取最大流水 + 1。"""
    await _add_doc(db, "DM-SOP-000001", "SOP")
    await _add_doc(db, "DM-SOP-000002", "SOP")
    assert await next_doc_id(db, "SOP") == "DM-SOP-000003"


async def test_next_doc_id_category_independent(db):
    """流水號依分類獨立：SOP 與 OTHER 各自計。"""
    await _add_doc(db, "DM-SOP-000005", "SOP")
    assert await next_doc_id(db, "SOP") == "DM-SOP-000006"
    assert await next_doc_id(db, "OTHER") == "DM-OTHER-000001"
