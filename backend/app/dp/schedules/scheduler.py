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
from datetime import datetime

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

# `CRON_EXPR` 的解讀時區（#517 裁示）。`0 8 * * *` 即**台灣時間** 08:00。
#
# 原為 `"UTC"`，於是 5 支排程全部晚 8 小時觸發——催辦信在下班時間寄、週報在週一傍晚才發。
# 規格（`spec_us13` FR-004a、ET `spec_us14` FR-02）只寫「週一 10:00」而從未指定時區，
# 實作選了 UTC，沒有人裁示過；2026-10-05 定案為台灣時間。
#
# 與 `core/db.py::_SESSION_TIMEZONE` 同一基準——該處 docstring 已明寫「全系統以台灣時間切日」，
# 排程原本是唯一沒跟上的一塊。
#
# ⚠️ 本常數是**解讀 cron 的時區**，與寫入 DB 的時間無關：`DP_SCHEDULE_LOG` 的起訖、
# `LAST_RUN_DATE` 一律走 `utcnow()`（UTC aware），不受此值影響。
#
# ⛔ **改成有 DST 的時區前，先想清楚兩種壞法。** `Asia/Taipei` 恆為 `+08:00`（實測 2026–2046
# 每 6 小時取樣，只有一種 offset），所以不存在「本地時刻不存在」與「本地時刻出現兩次」。
# 換成有日光節約的時區後，`0 2 30 * *` 這類設定會在切換日**不觸發**或**觸發兩次**，而
# APScheduler 不會報錯。日後若要把時區做成可設定，這是第一個該撞的牆。
_SCHEDULE_TIMEZONE = "Asia/Taipei"

# 動態 import 之縱深防禦：HANDLER_REF 僅允許平台 / 模組命名空間（縱使 DB 註冊表遭竄改亦無法載入
# os / subprocess 等任意模組。CWE-470 Unsafe Reflection）。
_ALLOWED_HANDLER_PREFIXES = ("app.dp.", "app.et.", "app.dm.")

_repo = ScheduleRepository()

# 進行中的 job task（供 lifespan 收斂時等待其寫完歷程，見 shutdown_scheduler）。
_inflight: set[asyncio.Task] = set()
# 排程引擎所在之 event loop（供同步 listener 以 run_coroutine_threadsafe 排非同步任務）。
_loop: asyncio.AbstractEventLoop | None = None
# 運行中的 scheduler 單例（供編輯端點即時 reschedule / add / remove；引擎未啟動時為 None）。
_scheduler: AsyncIOScheduler | None = None


def validate_cron(cron_expr: str) -> None:
    """驗證 cron 表達式合法；非法拋 ValueError（呼叫端轉 422）。"""
    CronTrigger.from_crontab(cron_expr, timezone=_SCHEDULE_TIMEZONE)


def next_run(cron_expr: str) -> "datetime | None":
    """由 cron 算「現在起」之下次觸發時間（供總覽顯示）；非法 cron 回 None。"""
    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=_SCHEDULE_TIMEZONE)
    except ValueError:
        return None
    return trigger.get_next_fire_time(None, utcnow())


def apply_job_change(job_id: str, *, cron_expr: str, is_enabled: bool, handler_ref: str) -> None:
    """將 DP_SCHEDULE 之變更即時套到運行中的引擎（啟用→add/reschedule、停用→remove）。

    引擎未啟動（如測試 / 非 leader）則 no-op——DB 已更新，於下次 start_scheduler 生效。
    """
    if _scheduler is None:
        return
    existing = _scheduler.get_job(job_id)
    if is_enabled:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=_SCHEDULE_TIMEZONE)
        if existing is not None:
            _scheduler.reschedule_job(job_id, trigger=trigger)
        else:
            _scheduler.add_job(
                _run_job,
                trigger=trigger,
                args=[job_id, handler_ref],
                id=job_id,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
    elif existing is not None:
        _scheduler.remove_job(job_id)


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
    global _loop, _scheduler
    if not scheduler_leader.is_leader():
        logger.info("本實例非排程 leader，略過排程引擎啟動")
        return None

    _loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(timezone=_SCHEDULE_TIMEZONE)
    scheduler.add_listener(_on_max_instances, EVENT_JOB_MAX_INSTANCES)

    async with AsyncSessionLocal() as db:
        jobs = await _repo.list_enabled(db)

    for job in jobs:
        scheduler.add_job(
            _run_job,
            trigger=CronTrigger.from_crontab(job.cron_expr, timezone=_SCHEDULE_TIMEZONE),
            args=[job.job_id, job.handler_ref],
            id=job.job_id,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("已註冊排程 job_id=%s cron=%s", job.job_id, job.cron_expr)

    scheduler.start()
    _scheduler = scheduler
    logger.info("排程引擎啟動，載入 %d 個啟用中 job", len(jobs))
    return scheduler


async def shutdown_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    """lifespan 收斂：暫停觸發新 job → **等進行中的 job 寫完歷程** → 關閉引擎。

    註：APScheduler 之 `AsyncIOExecutor.shutdown(wait=True)` 實際不等待、會 cancel 進行中的 task，
    故本函式自行 `gather` 追蹤中的 `_run_job` task 以確保 FR-03「每次執行 MUST 記錄」不因關閉遺失。
    """
    global _loop, _scheduler
    if scheduler is not None:
        scheduler.pause()  # 停止觸發新 job（已進行中的續跑）
        pending = [task for task in _inflight if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        scheduler.shutdown(wait=False)
        logger.info("排程引擎已關閉")
    _loop = None
    _scheduler = None
