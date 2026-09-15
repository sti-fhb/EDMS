"""US11 排程引擎整合測試（scheduler）。

直測 `run_and_log` / `write_skipped_log`（皆接收 db、不自開 session），不等真 cron 觸發。
涵蓋 AC1（執行 SUCCESS + 寫歷程 + LAST_RUN）/ AC3（失敗隔離 FAILED）/ AC4（SKIPPED）/ AC5（停用略過）。
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

import app.dp.schedules.scheduler as scheduler_mod
from app.dp.schedules.models import DpScheduleLog
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.scheduler import (
    run_and_log,
    shutdown_scheduler,
    start_scheduler,
    write_skipped_log,
)

pytestmark = pytest.mark.integration

# 測試用 handler（供 run_and_log 動態 import；job_id 用種子已存在之 SCHDP001 以滿足 FK）
_JOB = "SCHDP001"
_HANDLER_MOD = "tests.integration.dp.test_dp_schedule_engine"


async def _ok_handler() -> None:
    """成功 handler（無副作用）。"""


async def _boom_handler() -> None:
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _allow_test_handlers(monkeypatch):
    """放行 tests.* 命名空間之測試 handler（生產白名單僅 app.dp./app.et./app.dm.，見 _resolve_handler）。"""
    monkeypatch.setattr(
        scheduler_mod, "_ALLOWED_HANDLER_PREFIXES", scheduler_mod._ALLOWED_HANDLER_PREFIXES + ("tests.",)
    )


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


async def test_run_and_log_rejects_disallowed_handler_prefix(db, monkeypatch):
    """安全（縱深防禦）：HANDLER_REF 不在允許命名空間 → 拒絕解析、記 FAILED（不 importlib 任意模組）。"""
    # 還原為生產白名單（不含 tests.），驗證非法前綴被擋
    monkeypatch.setattr(scheduler_mod, "_ALLOWED_HANDLER_PREFIXES", ("app.dp.", "app.et.", "app.dm."))
    status = await run_and_log(db, _JOB, "os.system")

    assert status == "FAILED"
    assert "允許命名空間" in (await _logs(db))[0].error_msg


async def test_write_skipped_log(db):
    """AC4：前次未完成被丟棄 → 歷程 SKIPPED（END_DATE=null）+ LAST_RUN_STATUS=SKIPPED。"""
    await write_skipped_log(db, _JOB)

    logs = await _logs(db)
    assert logs[0].status == "SKIPPED"
    assert logs[0].end_date is None
    assert (await ScheduleRepository().get(db, _JOB)).last_run_status == "SKIPPED"


async def test_list_enabled_excludes_disabled(db):
    """AC5：引擎僅載入 `IS_ENABLED=true`。

    停用側以**本測試自己停用**的 job 驗，不借用某一列 seed 當下剛好是停用——那種寫法會
    在該 job 日後被接線啟用時無預警轉紅（#325 接上 SCHET001 / SCHET002 時即如此），而紅
    的原因與被測行為無關。
    """
    from sqlalchemy import update

    from app.dp.schedules.models import DpSchedule

    await db.execute(update(DpSchedule).where(DpSchedule.job_id == "SCHDM002").values(is_enabled=False))
    await db.flush()

    enabled = await ScheduleRepository().list_enabled(db)
    ids = {j.job_id for j in enabled}

    assert "SCHDP001" in ids
    assert "SCHDM002" not in ids, "停用中的 job 不得被引擎載入"
    # 沒有任何啟用中的 job 停留在預留的 placeholder——載入它會讓引擎每次觸發都 import
    # 失敗，寫一筆沒有人看的 FAILED 然後安靜地什麼都不做
    assert all(not j.handler_ref.endswith(".pending") for j in enabled)


async def test_list_all_includes_disabled(db):
    """總覽清單含停用 job。"""
    all_ids = {j.job_id for j in await ScheduleRepository().list_all(db)}
    assert {"SCHDP001", "SCHET001", "SCHET002", "SCHDM001"} <= all_ids


# ── wrapper 入口 / 引擎生命週期（生產環境實際執行路徑）─────────────────────


async def test_write_skipped_wrapper_commits(db, monkeypatch):
    """AC4：`_write_skipped` wrapper 自持 session + commit 落地（monkeypatch 用 fixture db 之 savepoint 隔離）。"""

    @asynccontextmanager
    async def _fake_session():
        yield db

    monkeypatch.setattr(scheduler_mod, "AsyncSessionLocal", _fake_session)
    await scheduler_mod._write_skipped(_JOB)

    logs = await _logs(db)
    assert len(logs) == 1 and logs[0].status == "SKIPPED"


async def test_run_job_wrapper_commits(db, monkeypatch):
    """AC1：`_run_job` wrapper 自持 session + commit；成功 handler → SUCCESS 歷程落地。"""

    @asynccontextmanager
    async def _fake_session():
        yield db

    monkeypatch.setattr(scheduler_mod, "AsyncSessionLocal", _fake_session)
    await scheduler_mod._run_job(_JOB, f"{_HANDLER_MOD}._ok_handler")

    logs = await _logs(db)
    assert len(logs) == 1 and logs[0].status == "SUCCESS"


async def test_start_scheduler_registers_enabled_and_shutdown(db):
    """AC1：`start_scheduler` 註冊啟用中 job；shutdown 不拋例外。

    ⚠️ 本測試**驗不到「停用者不註冊」**：`start_scheduler` 自開 `AsyncSessionLocal`
    （另一條連線），看不到測試交易內的改動，只讀得到 seed 的狀態；而 seed 的啟停狀態
    會隨各模組接線而變。該行為改由 `test_list_enabled_excludes_disabled` 覆蓋——那支吃
    測試 session，可以自己造出停用狀態。
    """
    scheduler = await start_scheduler()
    try:
        assert scheduler is not None
        assert scheduler.get_job("SCHDP001") is not None
    finally:
        await shutdown_scheduler(scheduler)
