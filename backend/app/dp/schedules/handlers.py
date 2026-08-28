"""平台自身排程 handler（US11 FR-05）。

`SCHDP001`（每日）＝ `daily_platform_job`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：
① 閒置帳號禁用 ② 密碼到期提醒 ③ 清理逾期待驗證列（#226）。

三批次各自交易、各自容錯，皆不讓失敗往外拋（前兩批逐筆 commit、第三批單一 DELETE 後 commit）
——否則單批失敗會讓下方的彙總 log 整條不寫，且 scheduler 的 job 級 catch-all 會把「兩批成功、
一批失敗」記成整個 SCHDP001 失敗。帳號生命週期邏輯歸使用者域（`UsersService`），本 handler
僅編排。handler 為 async 無參，自管 session。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dp.users.service import UsersService

logger = logging.getLogger(__name__)


async def daily_platform_job() -> None:
    """平台每日作業：閒置禁用 + 密碼到期提醒（兩批次分開 session、逐筆 commit 於 UsersService 內）。"""
    service = UsersService()

    async with AsyncSessionLocal() as db:
        disabled = await service.disable_idle_accounts(db)

    async with AsyncSessionLocal() as db:
        reminded = await service.send_pwd_expiry_reminders(db)

    async with AsyncSessionLocal() as db:
        purged = await service.purge_expired_pending(db)

    logger.info(
        "SCHDP001 完成：閒置禁用 %d 筆、密碼到期提醒 %d 筆、清理逾期待驗證列 %d 筆",
        disabled,
        reminded,
        purged,
    )
