"""簽核催辦每日批次 handler（US6 FR-006）。

`SCHDM002`（每日）＝ `run`（`DP_SCHEDULE.HANDLER_REF` 指向本 callable）：掃描停留 ≥
`DM_REMIND_THRESHOLD` 天之 PENDING 送審，對指定審核者以 `AUTO_REMIND` 催辦。handler 為 async 無參、
自管 session（比照 `app.dp.schedules.handlers.daily_platform_job`）。

註：`SCHDM001` 為「DM KPI 週報 + 未讀提醒」（週一），與本簽核催辦（每日）為不同 job；本 job 用 SCHDM002。
清單「停留天數標紅」之即時呈現於前端簽核中心（SA 裁示 Q1：催辦免站內訊息表）。
"""

import logging

from app.core.db import AsyncSessionLocal
from app.dm.review.center_service import ReviewCenterService
from app.services import ParamService

logger = logging.getLogger(__name__)

_REMIND_THRESHOLD_PARAM = "DM_REMIND_THRESHOLD"
_DEFAULT_THRESHOLD_DAYS = 7


async def run() -> None:
    """簽核催辦每日作業：停留 ≥ 門檻之 PENDING → AUTO_REMIND 通知指定審核者。"""
    async with AsyncSessionLocal() as db:
        threshold = await ParamService().get_int_param(db, _REMIND_THRESHOLD_PARAM, "VALUE", _DEFAULT_THRESHOLD_DAYS)
        count = await ReviewCenterService().scan_overdue_and_remind(db, threshold_days=threshold)
        await db.commit()
    logger.info("DM 簽核催辦完成：催辦 %d 筆（門檻 %d 天）", count, threshold)
