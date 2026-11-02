"""平台自身排程 handler（US11 FR-05）。

`SCHDP001`（每日）＝ `daily_platform_job`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：
① 閒置帳號禁用 ② 密碼到期提醒 ③ 清理逾期待驗證列（#226）
④ 遮罩逾連結時效之寄送失敗信件內文（#50）。

四批次各自交易、各自容錯，皆不讓失敗往外拋（前兩批逐筆 commit、後兩批單一敘述後 commit）
——否則單批失敗會讓下方的彙總 log 整條不寫，且 scheduler 的 job 級 catch-all 會把「三批成功、
一批失敗」記成整個 SCHDP001 失敗。帳號生命週期邏輯歸使用者域（`UsersService`）、outbox 遮罩
政策歸通知域（`app.dp.notify.redaction`），本 handler 僅編排。handler 為 async 無參，自管 session。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dp.notify.redaction import redact_expired_failed_mails
from app.dp.users.service import UsersService

logger = logging.getLogger(__name__)


async def daily_platform_job() -> None:
    """平台每日作業：四批次分開 session、各自 commit（見 module docstring）。"""
    service = UsersService()

    async with AsyncSessionLocal() as db:
        disabled = await service.disable_idle_accounts(db)

    async with AsyncSessionLocal() as db:
        reminded = await service.send_pwd_expiry_reminders(db)

    async with AsyncSessionLocal() as db:
        purged = await service.purge_expired_pending(db)

    async with AsyncSessionLocal() as db:
        redacted = await redact_expired_failed_mails(db)

    logger.info(
        "SCHDP001 完成：閒置禁用 %d 筆、密碼到期提醒 %d 筆、清理逾期待驗證列 %d 筆、遮罩逾時效失敗信件 %d 筆",
        disabled,
        reminded,
        purged,
        redacted,
    )
