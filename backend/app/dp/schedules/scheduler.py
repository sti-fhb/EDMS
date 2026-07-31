"""排程執行引擎（US11 FR-01~04）。

APScheduler（`AsyncIOScheduler`）於 FastAPI lifespan 啟動時自 `DP_SCHEDULE` 載入啟用中 job：
- `CRON_EXPR` → `CronTrigger.from_crontab`；`HANDLER_REF`（完整 dotted path 到 async 無參 callable）動態 import。
- `max_instances=1` + `coalesce`：前次未完成 → 本次丟棄，經 `EVENT_JOB_MAX_INSTANCES` listener 寫 `SKIPPED`。
- 每次執行結束單筆 INSERT `DP_SCHEDULE_LOG`（起訖 / 結果 / 錯誤）+ 更新 `LAST_RUN_*`；**單一 job 失敗隔離**。
- 多實例以 `scheduler_leader.is_leader()` 確保只有 leader 觸發（EDMS 單實例直跑）。
"""

import asyncio
import importlib
import logging

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobSubmissionEvent
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

# 動態 import 之縱深防禦：HANDLER_REF 僅允許平台 / 模組命名空間（縱使 DB 註冊表遭竄改亦無法載入
# os / subprocess 等任意模組。CWE-470 Unsafe Reflection）。
_ALLOWED_HANDLER_PREFIXES = ("app.dp.", "app.et.", "app.dm.")

_repo = ScheduleRepository()

# 進行中的 job task（供 lifespan 收斂時等待其寫完歷程，見 shutdown_scheduler）。
_inflight: set[asyncio.Task] = set()
# 排程引擎所在之 event loop（供同步 listener 以 run_coroutine_threadsafe 排非同步任務）。
_loop: asyncio.AbstractEventLoop | None = None


def _resolve_handler(handler_ref: str):
    """完整 dotted path → async 無參 callable（相容種子 `...daily_platform_job` 與慣例名 `run`）。

    白名單限縮 importlib 之 blast radius（縱深防禦，見 _ALLOWED_HANDLER_PREFIXES）。
    """
    if not handler_ref.startswith(_ALLOWED_HANDLER_PREFIXES):
        raise ValueError(f"HANDLER_REF 不在允許命名空間內：{handler_ref}")
    module_path, _, attr = handler_ref.rpartition(".")
    module = importlib.import_module(module_path)
    handler = getattr(module, attr)
    if not callable(handler):
        raise TypeError(f"HANDLER_REF 非 callable：{handler_ref}")
    return handler


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
    except Exception as exc:  # 逐 job 隔離：任何例外皆記 FAILED、不外拋阻斷排程器
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
    """排程觸發之入口（自持 session + commit）；登記進行中 task 供收斂等待。核心見 run_and_log。"""
    task = asyncio.current_task()
    if task is not None:
        _inflight.add(task)
    try:
        async with AsyncSessionLocal() as db:
            await run_and_log(db, job_id, handler_ref)
            await db.commit()
    except Exception:
        logger.exception("排程 job 歷程寫入失敗 job_id=%s", job_id)
    finally:
        if task is not None:
            _inflight.discard(task)


async def _write_skipped(job_id: str) -> None:
    """SKIPPED 寫入之入口（自持 session + commit）；核心見 write_skipped_log。"""
    try:
        async with AsyncSessionLocal() as db:
            await write_skipped_log(db, job_id)
            await db.commit()
    except Exception:
        logger.exception("排程 SKIPPED 歷程寫入失敗 job_id=%s", job_id)


def _on_max_instances(event: JobSubmissionEvent) -> None:
    """`EVENT_JOB_MAX_INSTANCES` 同步 listener → 於引擎 loop 排非同步任務寫 SKIPPED。"""
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(_write_skipped(event.job_id), _loop)


async def start_scheduler() -> AsyncIOScheduler | None:
    """lifespan 啟動：載入啟用中 job、註冊 cron、啟動引擎。非 leader 則不啟動（回 None）。"""
    global _loop
    if not scheduler_leader.is_leader():
        logger.info("本實例非排程 leader，略過排程引擎啟動")
        return None

    _loop = asyncio.get_running_loop()
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
    """lifespan 收斂：暫停觸發新 job → **等進行中的 job 寫完歷程** → 關閉引擎。

    註：APScheduler 之 `AsyncIOExecutor.shutdown(wait=True)` 實際不等待、會 cancel 進行中的 task，
    故本函式自行 `gather` 追蹤中的 `_run_job` task 以確保 FR-03「每次執行 MUST 記錄」不因關閉遺失。
    """
    global _loop
    if scheduler is not None:
        scheduler.pause()  # 停止觸發新 job（已進行中的續跑）
        pending = [task for task in _inflight if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        scheduler.shutdown(wait=False)
        logger.info("排程引擎已關閉")
    _loop = None
