"""KPI 週報 + 未讀提醒每週批次 handler（US13 FR-004~006）。

`SCHDM001`（每週，預設週一 10:00）＝ `run`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：計算全部
已發布文件 KPI → 寄 KPI 週報予所有 DM_ADMIN、未讀提醒予未看之閱覽者（逐人彙整一信）。handler 為 async
無參、自管 session（比照 `app.dm.review.reminder.run` / `app.dp.schedules.handlers`）。

執行時間由平台 `DP_SCHEDULE.CRON_EXPR` 決定，**且那是唯一的事實來源**——本 handler 與平台引擎
皆不讀 `DP_PARAM`。管理者於平台 DP 後台「排程管理」編輯 `CRON_EXPR`，經 `apply_job_change` 即時生效。

> 原本另有 `DP_PARAM.DM_WEEKLY_SCHED_DAY_TIME`，SA 裁示（Q1=A 2026-09-02）已認定它不參與排程決策、
> 但保留為「預設值紀錄」。**#332 進一步移除它**：那個「紀錄」沒有任何讀者，卻仍出現在 DP 後台且
> 看起來可編輯——管理者改了完全沒效果且無錯誤訊息。ET 側已於 #325 對 `ET_WEEKLY_STAT_DAY_TIME`
> 做同樣處置，兩模組現在一致。預設值本身寫在 `9eb4dd6e496b` 的 `_SCHDM001_CRON`。

與 SCHDM002（簽核催辦、每日）為不同 job。
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
