"""發信 worker（T019）。

常駐背景消費者（非排程 job，research §8）：輪詢 DP_EMAIL_LOG 之 PENDING 信件，
經 mailer 寄送、更新 SENT / 重試 / FAILED。核心 process_pending_once 為單次輪詢、
mailer 依賴注入（測試以 fake mailer 驗證，不需真 SMTP）；常駐迴圈於 main.py lifespan 起停（T020）。
"""

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository

# 系統作業更新者（DP_EMAIL_LOG 標準欄位 UPDATED_USER）
_SYSTEM_USER = "SYSTEM"


class Mailer(Protocol):
    """SMTP 寄送器介面；worker 依此注入（正式為 SmtpMailer，測試為 fake）。"""

    async def send(self, *, recipient: str, subject: str, body: str) -> None: ...


class EmailWorker:
    """outbox 消費者：單次輪詢寄送一批 PENDING。"""

    def __init__(self, repository: NotifyRepository | None = None) -> None:
        self._repo = repository or NotifyRepository()

    async def process_pending_once(
        self,
        db: AsyncSession,
        *,
        mailer: Mailer,
        max_retry: int,
        interval_minutes: int,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """處理一批 PENDING 信件；回傳本輪成功寄出的封數。

        單筆失敗不影響同批其他收件人（各自 try）；失敗累計 RETRY_COUNT，達 max_retry 標 FAILED，
        未達則留 PENDING 待下輪（依 interval_minutes 間隔）。

        Args:
            db: AsyncSession。
            mailer: 寄送器（注入）。
            max_retry: 重試上限（DP_PARAM MAIL.RETRY_MAX）。
            interval_minutes: 重試間隔分鐘（DP_PARAM MAIL.RETRY_INTERVAL_MIN）。
            now: 目前時間（預設 utcnow()，測試可注入）。
            limit: 單輪批量上限（近似 RATE_PER_MIN 限速；正式迴圈間隔搭配控制速率）。
        """
        current = now if now is not None else utcnow()
        rows = await self._repo.list_pending_for_attempt(
            db, limit=limit, interval_minutes=interval_minutes, now=current
        )
        sent = 0
        for row in rows:
            try:
                await mailer.send(recipient=row.recipient, subject=row.subject, body=row.body)
            except Exception as exc:  # mailer 為外部 SMTP，任何失敗皆轉重試 / FAILED，不得中斷同批
                row.retry_count += 1
                row.error_msg = str(exc)[:500]
                row.updated_user = _SYSTEM_USER
                row.updated_date = current
                if row.retry_count >= max_retry:
                    row.status = "FAILED"
            else:
                row.status = "SENT"
                row.sent_date = current
                row.updated_user = _SYSTEM_USER
                row.updated_date = current
                sent += 1
        await db.flush()
        return sent
