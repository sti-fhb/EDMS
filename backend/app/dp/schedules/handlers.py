"""平台自身排程 handler（US11 FR-05）。

`SCHDP001`（每日）＝ `daily_platform_job`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：
① 閒置帳號禁用 ② 密碼到期提醒。兩批次各自交易 / 逐筆容錯（見 UsersService）；帳號生命週期
邏輯歸使用者域（`UsersService`），本 handler 僅編排。handler 為 async 無參，自管 session。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dp.users.service import UsersService

logger = logging.getLogger(__name__)


async def daily_platform_job() -> None:
    """平台每日作業：閒置禁用 + 密碼到期提醒（兩批次分開交易，互不影響）。"""
    service = UsersService()

    async with AsyncSessionLocal() as db:
        disabled = await service.disable_idle_accounts(db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        reminded = await service.send_pwd_expiry_reminders(db)
        await db.commit()

    logger.info("SCHDP001 完成：閒置禁用 %d 筆、密碼到期提醒 %d 筆", disabled, reminded)
