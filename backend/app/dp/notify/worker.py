"""發信 worker（T019）。

常駐背景消費者（非排程 job，research §8）：輪詢 DP_EMAIL_LOG 之 PENDING 信件，
經 mailer 寄送、更新 SENT / 重試 / FAILED。核心 process_pending_once 為單次輪詢、
mailer 依賴注入（測試以 fake mailer 驗證，不需真 SMTP）；常駐迴圈於 main.py lifespan 起停（T020）。
"""

import asyncio
import logging
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository
from app.services import ParamService

logger = logging.getLogger(__name__)

# 系統作業更新者（DP_EMAIL_LOG 標準欄位 UPDATED_USER）
_SYSTEM_USER = "SYSTEM"

# MAIL 參數讀取失敗時的保底值（對齊 T009 種子）
_DEFAULT_RETRY_MAX = 5
_DEFAULT_RETRY_INTERVAL_MIN = 2
_DEFAULT_RATE_PER_MIN = 60
_POLL_INTERVAL_SECONDS = 60


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


async def _read_mail_params(db: AsyncSession) -> tuple[int, int, int]:
    """自 DP_PARAM MAIL 讀 (RETRY_MAX, RETRY_INTERVAL_MIN, RATE_PER_MIN)；缺 / 非數字用保底值。"""
    param = ParamService()

    async def _int(key: str, default: int) -> int:
        raw = await param.get_param_value(db, "MAIL", key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    return (
        await _int("RETRY_MAX", _DEFAULT_RETRY_MAX),
        await _int("RETRY_INTERVAL_MIN", _DEFAULT_RETRY_INTERVAL_MIN),
        await _int("RATE_PER_MIN", _DEFAULT_RATE_PER_MIN),
    )


async def run_forever(
    mailer: Mailer, stop_event: asyncio.Event, *, poll_interval_seconds: int = _POLL_INTERVAL_SECONDS
) -> None:
    """常駐輪詢迴圈（main.py lifespan 起停）：每輪讀 MAIL 參數 → 處理一批 → sleep。

    每輪自持 db session 並 commit（與呼叫方交易無關）；單輪例外記 log 不中斷迴圈；
    stop_event 設定時優雅收斂。速率近似：每輪最多 RATE_PER_MIN 封、輪距 poll_interval_seconds。
    """
    worker = EmailWorker()
    logger.info("發信 worker 啟動")
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as db:
                max_retry, interval, rate = await _read_mail_params(db)
                await worker.process_pending_once(
                    db, mailer=mailer, max_retry=max_retry, interval_minutes=interval, limit=rate
                )
                await db.commit()
        except Exception:
            logger.exception("發信 worker 輪詢失敗")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass
    logger.info("發信 worker 收斂")
