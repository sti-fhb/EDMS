"""ET 排程 handler（US14 / #325）。

`SCHET002`（每日）＝ `daily_job`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：
① 到期自動關閉 ② 結清逾期未提交之作答。

handler 為 async 無參、自管 session（比照 `app.dp.schedules.handlers.daily_platform_job`
與 `app.dm.review.reminder.run`）。

## 兩批各自交易

第二批失敗不該讓第一批已完成的關閉一起回滾——那會讓「課程到期了卻還開著」這件事在
結清邏輯出錯時無限延續，而那正是本 job 要修的狀態。同一個理由見 `daily_platform_job`
的三批次拆法。

## 順序：先關閉、後結清

剛被第一批關掉的課程，其未提交作答要在**同一次執行**內被第二批掃到；反過來會讓每門
課的結清都慢一天。第二批的母體是「所有視同關閉」，不限於本次剛關的，故即使第一批
全部失敗，先前已關閉課程的結清照常進行。

## SCHET001 尚未實作

`SCHET001`（每週統計與週報）之 handler 待 ET-16 第二段交付；在那之前該列於
`DP_SCHEDULE` 維持 `IS_ENABLED = false`，引擎不會嘗試載入它。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.et.schedules.service import EtScheduleService

logger = logging.getLogger(__name__)


async def daily_job() -> None:
    """SCHET002 每日作業：到期關閉 + 結清逾期未提交之作答。"""
    service = EtScheduleService()

    async with AsyncSessionLocal() as db:
        closed = await service.close_expired_courses(db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        settled = await service.settle_stale_attempts(db)
        await db.commit()

    logger.info("SCHET002 完成：到期關閉 %d 門、結清逾期作答 %d 筆", closed, settled)
