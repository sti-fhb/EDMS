"""跨模組教材引用（US12）資料存取：取當前發布版 / 列 TRAINING 清單 / 分類存在 / 取版本檔。

唯讀查詢（ET→DM in-process，供 DmDocumentService 門面）；跨子模組（同屬 DM）直接引用 Model。
"""

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.catalog.models import DmCategory
from app.dm.document.models import DmDocument, DmDocVersion

_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
# 對外有效（可供 ET 引用清單）之文件狀態：在架（含廢止待簽核，仍對外有效）；OBSOLETE 不列。
_LIST_STATUSES = (_PUBLISHED, _PENDING_OBSOLETE)
# LIKE 萬用字元轉義（keyword 防「% 命中全部」；值仍走參數化綁定）
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


class IntegrationRepository:
    """US12 跨模組取用查詢。"""

    async def get_document(self, db: AsyncSession, doc_id: str) -> DmDocument | None:
        return await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id, DmDocument.deleted == 0))

    async def get_version(self, db: AsyncSession, version_id: int) -> DmDocVersion | None:
        return await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == version_id))

    async def category_exists(self, db: AsyncSession, category: str) -> bool:
        """分類碼是否存在（SRVDM002 之 INVALID_CATEGORY 防呆）。"""
        return bool(
            await db.scalar(select(DmCategory.category_code).where(DmCategory.category_code == category).limit(1))
        )

    async def list_training(self, db: AsyncSession, *, category: str, keyword: str, func_code: str | None) -> list[Row]:
        """列該分類「有當前發布版且在架」之文件（發布時間 DESC；選填名稱關鍵字 / func_code）。"""
        stmt = (
            select(
                DmDocument.doc_id,
                DmDocument.doc_name,
                DmDocVersion.version_no,
                DmDocVersion.published_date,
            )
            .join(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .where(
                DmDocument.category_code == category,
                DmDocument.deleted == 0,
                DmDocument.current_version_id.is_not(None),
                DmDocument.status.in_(_LIST_STATUSES),
            )
            .order_by(DmDocVersion.published_date.desc())
        )
        if keyword:
            esc = keyword.translate(_LIKE_ESCAPE)
            stmt = stmt.where(DmDocument.doc_name.ilike(f"%{esc}%", escape="\\"))
        if func_code:
            stmt = stmt.where(DmDocument.func_code == func_code)
        return list((await db.execute(stmt)).all())
