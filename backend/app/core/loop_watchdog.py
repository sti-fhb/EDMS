"""event loop 卡住時自動結束程式，交給容器重啟（#905 B16）。

## 為什麼在程式內做

#896 的健康檢查只把容器標成 unhealthy：Docker 非 swarm 模式不會因此重啟。autoheal 之類的容器要掛
Docker socket（等同主機 root），這台 VM 同時跑血庫系統，不划算。

後端只有一個 worker、一個 event loop。loop 被同步程式卡住時，所有請求、排程、發信 worker 一起停擺，
而行程還活著、`restart: unless-stopped` 不會動作——只能等人發現後手動重啟。

## 怎麼做

用 `faulthandler.dump_traceback_later(T, exit=True)`：loop 上的 task 每 `_TICK_SEC` 秒重設一次計時器；
loop 卡住約 T 秒（最後一次重設後 T 秒）、計時器沒被重設，就印出**所有 thread 的堆疊**到 stderr
（`docker logs` 看得到卡在哪），再以結束碼 1 結束，由容器重啟策略拉起來。

- 計時器跑在獨立的 C thread、**不需要 GIL**：Python 卡在死迴圈時照樣觸發。自己開 Python thread 做
  就做不到這點
- 堆疊只有 `File "...", line N in 函式名`：不含原始碼行、變數值與例外訊息，不會帶出個資
- ⚠️ 觸發時是硬結束（`_exit`），門檻要遠大於任何正當的卡頓（見 `config.EVENT_LOOP_WATCHDOG_SEC`）。代價：
  - 處理中的請求失敗；交易由 PostgreSQL 在連線斷開時回滾，稽核鏈的 advisory lock 是交易級的、一併釋放
  - 發信 worker 已寄出未寫回的那一封，重啟後再寄一次（「至少寄一次」，見 `dp/notify/worker`）
  - 上傳暫存：multipart 的暫存檔建立時即 unlink、行程結束就回收；ET 影片的 `.tmp/` 殘檔由每日孤兒清理處理
  - 排程：記憶體 jobstore、`misfire_grace_time` 為預設，重啟若碰上排程時間點，那一次跳過、等下一個時間點
    （每日作業即延後一天）；被打斷的那次在 `DP_SCHEDULE_LOG` 沒有紀錄，只看得到 `docker logs`
  - 行程內的限流與冷卻計數歸零
- ⚠️ `dump_traceback_later` 是**全域唯一**的計時器：pytest 的 `faulthandler_timeout` 也用它，兩者會互相
  覆蓋（本專案未設該選項）
"""

import asyncio
import contextlib
import faulthandler
import logging
import sys

logger = logging.getLogger(__name__)

#: 重設計時器的間隔。遠小於門檻即可；太短只是多幾次無謂的排程
_TICK_SEC = 5.0


async def _rearm_forever(timeout_sec: float) -> None:
    try:
        while True:
            faulthandler.dump_traceback_later(timeout_sec, exit=True, file=sys.stderr)
            await asyncio.sleep(min(_TICK_SEC, timeout_sec / 4))
    finally:
        faulthandler.cancel_dump_traceback_later()


def _report_unexpected_end(task: asyncio.Task) -> None:
    """task 不是被 `stop()` 取消而結束：watchdog 已失效，要讓人看得到（code review H1）。"""
    if not task.cancelled() and task.exception() is not None:
        logger.error("event loop watchdog 意外結束，已失效", exc_info=task.exception())


def start(timeout_sec: float) -> asyncio.Task | None:
    """在目前的 event loop 上啟用 watchdog；`timeout_sec` 為 0 時不啟用、回 None。"""
    if timeout_sec <= 0:
        return None
    logger.info("event loop watchdog 啟用 timeout_sec=%s", timeout_sec)
    task = asyncio.create_task(_rearm_forever(timeout_sec), name="event-loop-watchdog")
    task.add_done_callback(_report_unexpected_end)
    return task


async def stop(task: asyncio.Task | None) -> None:
    """停用 watchdog 並取消計時器。關閉流程可能超過門檻（等發信 worker 收斂等），要先停。

    ⚠️ 不可往外拋：這是 lifespan 關閉流程的第一行，一拋後面的排程關閉、等發信 worker 收斂全被跳過。
    task 先前因例外結束時，例外已由 `_report_unexpected_end` 記過。
    """
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
