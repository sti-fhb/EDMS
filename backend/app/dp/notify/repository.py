from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.notify.models import DpEmailLog, DpNotifyTemplate


class NotifyRepository:
    """通知範本查詢 + 寄件 outbox 存取（DP_NOTIFY_TEMPLATE / DP_EMAIL_LOG）。"""

    async def get_template(self, db: AsyncSession, module: str, template_code: str) -> DpNotifyTemplate | None:
        """取範本；不存在回 None（軟刪除項排除）。"""
        stmt = select(DpNotifyTemplate).where(
            DpNotifyTemplate.module == module,
            DpNotifyTemplate.template_code == template_code,
            DpNotifyTemplate.deleted == 0,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_log(self, db: AsyncSession, values: dict) -> None:
        """新增一列 outbox；只 flush（commit 由呼叫方交易負責）。"""
        db.add(DpEmailLog(**values))
        await db.flush()

    async def list_pending(self, db: AsyncSession, limit: int) -> list[DpEmailLog]:
        """取待寄（PENDING）信件，依建立時間序（用 (STATUS, CREATED_DATE) 索引）。"""
        stmt = (
            select(DpEmailLog)
            .where(DpEmailLog.status == "PENDING")
            .order_by(DpEmailLog.created_date, DpEmailLog.message_id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
