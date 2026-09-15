"""ET 排程 handler（US14 / #325）。

`SCHET002`（每日）＝ `daily_job`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：
① 到期自動關閉 ② 結清逾期未提交之作答。

handler 為 async 無參、自管 session（比照 `app.dp.schedules.handlers.daily_platform_job`
與 `app.dm.review.reminder.run`）。

## 兩批各自 session，且 service 內**逐筆** commit

第二批失敗不該讓第一批已完成的關閉一起回滾——那會讓「課程到期了卻還開著」這件事在
結清邏輯出錯時無限延續，而那正是本 job 要修的狀態。同一個理由見 `daily_platform_job`
的三批次拆法。

交易邊界在 `EtScheduleService` 內、以**單筆**為單位（見該模組 docstring 的兩個理由：
批次容錯與稽核鏈鎖的持有時間），故本層**不呼叫 `commit()`**——那會是一個永遠沒有東西
可提交的呼叫，讀者卻會以為交易邊界在這裡。

## 順序：先關閉、後結清

剛被第一批關掉的課程，其未提交作答要在**同一次執行**內被第二批掃到；反過來會讓每門
課的結清都慢一天。第二批的母體是「所有視同關閉」，不限於本次剛關的，故即使第一批
全部失敗，先前已關閉課程的結清照常進行。

`SCHET001`（每週）＝ `weekly_job`：① 統計快照 ② 週報 ③ 每週未看提醒。

## 快照與寄信分離

FR-ET-US14-09 明訂「寄送失敗 MUST NOT 影響已寫入之統計快照資料」。故快照與寄信是各自
獨立的 session 與交易，不是同一個交易裡的 try/except——後者仍會讓兩件事共用交易邊界，
寄信階段的任何回滾都可能把快照一起帶走。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.et.schedules.service import EtScheduleService
from app.et.schedules.weekly_service import EtWeeklyReportService
from app.et.stats.service import EtStatsService

logger = logging.getLogger(__name__)


async def weekly_job() -> None:
    """SCHET001 每週作業：統計快照 + 週報 + 每週未看提醒。"""
    async with AsyncSessionLocal() as db:
        written = await EtStatsService().take_snapshots(db)

    async with AsyncSessionLocal() as db:
        reports, reminds = await EtWeeklyReportService().send_weekly(db)

    logger.info("SCHET001 完成：快照 %d 筆、週報 %d 封、未看提醒 %d 封", written, reports, reminds)


async def daily_job() -> None:
    """SCHET002 每日作業：到期關閉 + 結清逾期未提交之作答。"""
    service = EtScheduleService()

    async with AsyncSessionLocal() as db:
        closed = await service.close_expired_courses(db)

    async with AsyncSessionLocal() as db:
        settled = await service.settle_stale_attempts(db)

    logger.info("SCHET002 完成：到期關閉 %d 門、結清逾期作答 %d 筆", closed, settled)
