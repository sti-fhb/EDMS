"""KPI 週報 + 未讀提醒每週批次 handler（US13 FR-004~006）。

`SCHDM001`（每週，預設週一 10:00）＝ `run`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：計算全部
已發布文件 KPI → 寄 KPI 週報予所有 DM_ADMIN、未讀提醒予未看之閱覽者（逐人彙整一信）。handler 為 async
無參、自管 session（比照 `app.dm.review.reminder.run` / `app.dp.schedules.handlers`）。

執行時間由平台 `DP_SCHEDULE.CRON_EXPR` 決定（SA 裁示 Q1=A 2026-09-02：CRON_EXPR 為單一事實來源，
管理者於平台 DP 排程後台編輯；`DM_WEEKLY_SCHED_DAY_TIME` 僅為預設值紀錄）。與 SCHDM002（簽核催辦、
每日）為不同 job。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dm.kpi.service import KpiService

logger = logging.getLogger(__name__)


async def run() -> None:
    """每週 KPI 週報 + 未讀提醒批次。"""
    async with AsyncSessionLocal() as db:
        result = await KpiService().run_weekly(db)
        await db.commit()
    logger.info(
        "DM KPI 週報完成：文件 %d、週報排入 %d、未讀提醒 %d 位閱覽者",
        result.total_docs,
        result.weekly_queued,
        result.unread_notified,
    )
