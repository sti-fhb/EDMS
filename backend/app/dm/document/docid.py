"""DOC_ID 產生器（T017）。

格式 `DM-{分類碼}-{6 位零填補流水號}`（如 DM-SOP-000123）；流水號**依分類各自獨立**、
草稿建立時配號（research §2）。零填補 6 位使字串序＝數值序，故取 MAX(DOC_ID) 即最新號。

並發下同分類兩草稿可能算到同一號 → 由 DOC_ID PK 擋下，呼叫端（US5）以重試處理；
本 Foundation 僅提供產號核心。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.document.models import DmDocument

_PREFIX = "DM"


def format_doc_id(category_code: str, seq: int) -> str:
    """組 DOC_ID（純函式）：DM-{分類碼}-{6 位零填補}。"""
    return f"{_PREFIX}-{category_code}-{seq:06d}"


async def next_doc_id(db: AsyncSession, category_code: str) -> str:
    """取該分類下一個 DOC_ID（現有最大流水號 + 1；無則從 000001 起）。"""
    pattern = f"{_PREFIX}-{category_code}-%"
    max_id = await db.scalar(select(func.max(DmDocument.doc_id)).where(DmDocument.doc_id.like(pattern)))
    if max_id is None:
        return format_doc_id(category_code, 1)
    seq = int(max_id.rsplit("-", 1)[1]) + 1
    return format_doc_id(category_code, seq)
