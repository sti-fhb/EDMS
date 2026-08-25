"""文件廢止申請（US8）資料存取：發起所需之最小查詢。"""

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.document.models import DmDocument
from app.dp.users.models import DpUser


class ObsoleteRepository:
    """廢止發起所需查詢（文件主檔、審核者 Email）。"""

    async def get_document(self, db: AsyncSession, doc_id: str) -> DmDocument | None:
        """取未刪除文件（供狀態判定與轉 PENDING_OBSOLETE）。"""
        return await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id, DmDocument.deleted == 0))

    async def get_user_name_email(self, db: AsyncSession, user_id: str) -> Row | None:
        """取使用者姓名 / Email（廢止送審通知 OBS_SUBMIT 用）。"""
        return (
            await db.execute(
                select(DpUser.user_name, DpUser.email).where(DpUser.user_id == user_id, DpUser.deleted == 0)
            )
        ).first()
