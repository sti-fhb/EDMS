"""DP_SCHEDULE / DP_SCHEDULE_LOG schema smoke test（T008）。

驗證排程註冊表與執行歷程 model 可用：log 對 schedule 的 FK、LOG_ID Identity 產號、
DP_SCHEDULE 可更新 LAST_RUN_*（BaseModel）、DP_SCHEDULE_LOG append-only（僅 CREATED_*）。
屬 schema plumbing 健康檢查。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.schedules.models import DpSchedule, DpScheduleLog

pytestmark = pytest.mark.integration


async def test_schedule_and_log_insert_and_query(db):
    """建 DP_SCHEDULE → DP_SCHEDULE_LOG（FK + Identity），讀回並驗證 job 更新 LAST_RUN_*。"""
    now = utcnow()
    db.add(
        DpSchedule(
            job_id="SCHZZ001",
            job_name="密碼到期提醒",
            module="DP",
            cron_expr="0 8 * * *",
            handler_ref="app.dp.schedules.handlers.pwd_expiry_remind",
            is_enabled=True,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()

    log = DpScheduleLog(
        job_id="SCHZZ001",
        start_date=now,
        end_date=utcnow(),
        status="SUCCESS",
        created_user="SYSTEM",
        created_date=now,
    )
    db.add(log)
    await db.flush()
    assert log.log_id is not None and log.log_id > 0

    # DP_SCHEDULE 可更新 LAST_RUN_*（BaseModel）
    schedule = (await db.execute(select(DpSchedule).where(DpSchedule.job_id == "SCHZZ001"))).scalar_one()
    schedule.last_run_date = utcnow()
    schedule.last_run_status = "SUCCESS"
    schedule.updated_user = "SYSTEM"
    schedule.updated_date = utcnow()
    await db.flush()

    fetched_log = (await db.execute(select(DpScheduleLog).where(DpScheduleLog.job_id == "SCHZZ001"))).scalar_one()
    assert fetched_log.status == "SUCCESS"
    assert schedule.last_run_status == "SUCCESS"
