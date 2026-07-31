"""排程執行引擎（US11 FR-01~04）。

APScheduler（`AsyncIOScheduler`）於 FastAPI lifespan 啟動時自 `DP_SCHEDULE` 載入啟用中 job：
- `CRON_EXPR` → `CronTrigger.from_crontab`；`HANDLER_REF`（完整 dotted path 到 async 無參 callable）動態 import。
- `max_instances=1` + `coalesce`：前次未完成 → 本次丟棄，經 `EVENT_JOB_MAX_INSTANCES` listener 寫 `SKIPPED`。
- 每次執行結束單筆 INSERT `DP_SCHEDULE_LOG`（起訖 / 結果 / 錯誤）+ 更新 `LAST_RUN_*`；**單一 job 失敗隔離**。
- 多實例以 `scheduler_leader.is_leader()` 確保只有 leader 觸發（EDMS 單實例直跑）。
"""

import importlib
import logging

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.utils import utcnow
from app.dp.schedules import scheduler_leader
from app.dp.schedules.repository import ScheduleRepository

logger = logging.getLogger(__name__)

_STATUS_SUCCESS = "SUCCESS"
_STATUS_FAILED = "FAILED"
_STATUS_SKIPPED = "SKIPPED"

_repo = ScheduleRepository()


def _resolve_handler(handler_ref: str):
    """完整 dotted path → async 無參 callable（相容種子 `...daily_platform_job` 與慣例名 `run`）。"""
    module_path, _, attr = handler_ref.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


async def run_and_log(db: AsyncSession, job_id: str, handler_ref: str) -> str:
    """執行單一 job 並寫歷程 + 更新 LAST_RUN（**不 commit**，交呼叫方）；**例外隔離**回傳最終 status。

    動態 import handler → await（handler 自管其業務 session）；任何例外皆記 FAILED，不外拋阻斷排程器。
    """
    start = utcnow()
    status = _STATUS_SUCCESS
    error_msg: str | None = None
    try:
        handler = _resolve_handler(handler_ref)
        await handler()
    except Exception as exc:  # noqa: BLE001 — 逐 job 隔離，任何例外皆記 FAILED、不外拋
        status = _STATUS_FAILED
        error_msg = str(exc)[:1000]
        logger.exception("排程 job 執行失敗 job_id=%s", job_id)
    end = utcnow()
    await _repo.insert_log(db, job_id=job_id, start_date=start, end_date=end, status=status, error_msg=error_msg)
    await _repo.update_last_run(db, job_id=job_id, run_date=end, status=status)
    return status


async def write_skipped_log(db: AsyncSession, job_id: str) -> None:
    """前次未完成而被丟棄 → 記 SKIPPED（END_DATE=null）+ 更新 LAST_RUN_STATUS（**不 commit**）。"""
    now = utcnow()
    await _repo.insert_log(
        db,
        job_id=job_id,
        start_date=now,
        end_date=None,
        status=_STATUS_SKIPPED,
        error_msg="前次執行尚未完成，跳過本次",
    )
    await _repo.update_last_run(db, job_id=job_id, run_date=now, status=_STATUS_SKIPPED)


async def _run_job(job_id: str, handler_ref: str) -> None:
    """排程觸發之入口（自持 session + commit）；核心邏輯見 run_and_log。"""
    try:
        async with AsyncSessionLocal() as db:
            await run_and_log(db, job_id, handler_ref)
            await db.commit()
    except Exception:
        logger.exception("排程 job 歷程寫入失敗 job_id=%s", job_id)


async def _write_skipped(job_id: str) -> None:
    """SKIPPED 寫入之入口（自持 session + commit）；核心見 write_skipped_log。"""
    try:
        async with AsyncSessionLocal() as db:
            await write_skipped_log(db, job_id)
            await db.commit()
    except Exception:
        logger.exception("排程 SKIPPED 歷程寫入失敗 job_id=%s", job_id)


def _on_max_instances(event: JobExecutionEvent) -> None:
    """`EVENT_JOB_MAX_INSTANCES` 同步 listener → 排非同步任務寫 SKIPPED。"""
    import asyncio

    asyncio.get_event_loop().create_task(_write_skipped(event.job_id))


async def start_scheduler() -> AsyncIOScheduler | None:
    """lifespan 啟動：載入啟用中 job、註冊 cron、啟動引擎。非 leader 則不啟動（回 None）。"""
    if not scheduler_leader.is_leader():
        logger.info("本實例非排程 leader，略過排程引擎啟動")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_listener(_on_max_instances, EVENT_JOB_MAX_INSTANCES)

    async with AsyncSessionLocal() as db:
        jobs = await _repo.list_enabled(db)

    for job in jobs:
        scheduler.add_job(
            _run_job,
            trigger=CronTrigger.from_crontab(job.cron_expr, timezone="UTC"),
            args=[job.job_id, job.handler_ref],
            id=job.job_id,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("已註冊排程 job_id=%s cron=%s", job.job_id, job.cron_expr)

    scheduler.start()
    logger.info("排程引擎啟動，載入 %d 個啟用中 job", len(jobs))
    return scheduler


async def shutdown_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    """lifespan 收斂：等待當前 job 跑完後關閉。"""
    if scheduler is not None:
        scheduler.shutdown(wait=True)
        logger.info("排程引擎已關閉")
