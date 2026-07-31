"""US11 排程引擎整合測試（scheduler）。

直測 `run_and_log` / `write_skipped_log`（皆接收 db、不自開 session），不等真 cron 觸發。
涵蓋 AC1（執行 SUCCESS + 寫歷程 + LAST_RUN）/ AC3（失敗隔離 FAILED）/ AC4（SKIPPED）/ AC5（停用略過）。
"""

import pytest
from sqlalchemy import select

from app.dp.schedules.models import DpScheduleLog
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.scheduler import run_and_log, write_skipped_log

pytestmark = pytest.mark.integration

# 測試用 handler（供 run_and_log 動態 import；job_id 用種子已存在之 SCHDP001 以滿足 FK）
_JOB = "SCHDP001"
_HANDLER_MOD = "tests.integration.dp.test_dp_schedule_engine"


async def _ok_handler() -> None:
    """成功 handler（無副作用）。"""


async def _boom_handler() -> None:
    raise RuntimeError("boom")


async def _logs(db, job_id=_JOB):
    return list((await db.execute(select(DpScheduleLog).where(DpScheduleLog.job_id == job_id))).scalars().all())


async def test_run_and_log_success_writes_log_and_last_run(db):
    """AC1：成功執行 → 歷程 SUCCESS（含起訖）+ 更新 DP_SCHEDULE.LAST_RUN_*。"""
    status = await run_and_log(db, _JOB, f"{_HANDLER_MOD}._ok_handler")

    assert status == "SUCCESS"
    logs = await _logs(db)
    assert len(logs) == 1
    assert logs[0].status == "SUCCESS"
    assert logs[0].start_date is not None and logs[0].end_date is not None
    assert logs[0].error_msg is None

    job = await ScheduleRepository().get(db, _JOB)
    assert job.last_run_status == "SUCCESS" and job.last_run_date is not None


async def test_run_and_log_failure_records_failed(db):
    """AC3：handler 拋例外 → 歷程 FAILED + 錯誤訊息（例外不外拋、隔離）。"""
    status = await run_and_log(db, _JOB, f"{_HANDLER_MOD}._boom_handler")

    assert status == "FAILED"
    logs = await _logs(db)
    assert logs[0].status == "FAILED"
    assert "boom" in logs[0].error_msg
    assert (await ScheduleRepository().get(db, _JOB)).last_run_status == "FAILED"


async def test_run_and_log_bad_handler_ref_isolated(db):
    """AC3：handler_ref 無法解析（不存在）→ FAILED，不使引擎崩潰。"""
    status = await run_and_log(db, _JOB, f"{_HANDLER_MOD}._not_exist")

    assert status == "FAILED"
    assert (await _logs(db))[0].status == "FAILED"


async def test_write_skipped_log(db):
    """AC4：前次未完成被丟棄 → 歷程 SKIPPED（END_DATE=null）+ LAST_RUN_STATUS=SKIPPED。"""
    await write_skipped_log(db, _JOB)

    logs = await _logs(db)
    assert logs[0].status == "SKIPPED"
    assert logs[0].end_date is None
    assert (await ScheduleRepository().get(db, _JOB)).last_run_status == "SKIPPED"


async def test_list_enabled_excludes_disabled(db):
    """AC5：引擎僅載入 IS_ENABLED=true（種子 SCHDP001 啟用；SCHET/SCHDM 預留停用不載入）。"""
    enabled = await ScheduleRepository().list_enabled(db)
    ids = {j.job_id for j in enabled}

    assert "SCHDP001" in ids
    assert "SCHET001" not in ids and "SCHDM001" not in ids


async def test_list_all_includes_disabled(db):
    """總覽清單含停用 job。"""
    all_ids = {j.job_id for j in await ScheduleRepository().list_all(db)}
    assert {"SCHDP001", "SCHET001", "SCHET002", "SCHDM001"} <= all_ids
