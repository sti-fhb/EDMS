"""簽核催辦每日批次 handler（US6 FR-006）。

`SCHDM002`（每日）＝ `run`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：掃描停留 ≥
`DM_REMIND_THRESHOLD` 天之 PENDING 送審，對指定審核者以 `AUTO_REMIND` 催辦。handler 為 async 無參、
自管 session（比照 `app.dp.schedules.handlers.daily_platform_job`）。

註：`SCHDM001` 為「DM KPI 週報 + 未讀提醒」（週一），與本簽核催辦（每日）為不同 job；本 job 用 SCHDM002。

催辦的出口**只有 Email**（#627 起 `AUTO_REMIND` 之 `CHANNEL` 為 `EMAIL`）。SA 裁示 Q1
「催辦免站內訊息表」排除的是站內訊息，不是排除全部出口；平台至今也沒有站內訊息佇列。
簽核中心清單的「停留天數標紅」是**人進畫面時**才看得到的輔助呈現，無法取代推送——
催辦針對的正是已經很久沒進畫面的人。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dm.review.center_service import (
    REMIND_THRESHOLD_DEFAULT,
    REMIND_THRESHOLD_PARAM,
    ReviewCenterService,
)
from app.services import ParamService

logger = logging.getLogger(__name__)


async def run() -> None:
    """簽核催辦每日作業：停留 ≥ 門檻之 PENDING → AUTO_REMIND 通知指定審核者。"""
    async with AsyncSessionLocal() as db:
        threshold = await ParamService().get_int_param(db, REMIND_THRESHOLD_PARAM, "VALUE", REMIND_THRESHOLD_DEFAULT)
        count = await ReviewCenterService().scan_overdue_and_remind(db, threshold_days=threshold)
        await db.commit()
    # 文案刻意寫「已排入寄信」而非「催辦」：#627 之前 `count` 是**掃到的筆數**，範本不寄信
    # 的那兩個月這行每天照報「催辦 N 筆」。現在 `count` 只數真的進 outbox 的，文案要跟著說清楚
    # 它數的是什麼，否則下一個人仍會把這個數字讀成「有 N 個人被催到」。
    # 掃到但沒排入者（帳號停用 / 範本停用 / 渲染失敗）各自在 `scan_overdue_and_remind` 留 warning。
    logger.info("DM 簽核催辦完成：已排入寄信 %d 筆（門檻 %d 天）", count, threshold)
