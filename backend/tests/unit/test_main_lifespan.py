"""main.py lifespan 單元測試：發信 worker task 隨 app 起停（patch run_forever，免連 DB）。"""

import asyncio

import pytest

from main import app, lifespan

pytestmark = pytest.mark.unit


async def test_lifespan_starts_and_stops_worker(monkeypatch):
    """進入 lifespan 啟動 worker task；離開時 stop_event 觸發，worker 優雅收斂、無例外。"""
    started = asyncio.Event()

    async def _fake_run(mailer, stop_event, **kwargs):
        started.set()
        await stop_event.wait()  # 收到停止訊號才返回（模擬優雅收斂）

    monkeypatch.setattr("main.run_forever", _fake_run)

    # 排程引擎（US11）需連 DB 載入 DP_SCHEDULE，於本「免連 DB」lifespan 單元測試以 stub 隔離
    # （引擎有專屬整合測試 test_dp_schedule_engine.py）。
    async def _fake_start():
        return None

    async def _fake_shutdown(scheduler):
        return None

    monkeypatch.setattr("main.start_scheduler", _fake_start)
    monkeypatch.setattr("main.shutdown_scheduler", _fake_shutdown)

    # 密碼運算執行緒池的暖機 / 關機也要隔離（#214）：真實 shutdown() 會**永久**關閉模組層級
    # 單例，之後任何用到密碼雜湊的測試都會拋 RuntimeError: cannot schedule new futures
    # after shutdown。本檔目前恰好是字母序最後一個測試檔而倖免，但那不是隔離設計。
    async def _fake_warm_up() -> None:
        return None

    monkeypatch.setattr("main.warm_up_password_backend", _fake_warm_up)
    monkeypatch.setattr("main.shutdown_password_executor", lambda: None)

    async with lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)
        assert started.is_set()
    # 離開 context 後 _fake_run 已優雅返回（未逾時強制取消）


async def test_lifespan_passes_configured_poll_interval_to_worker(monkeypatch):
    """worker 輪距取自 settings.MAIL_WORKER_POLL_INTERVAL_SECONDS（E2E 縮短用，#57）。"""
    received: dict[str, object] = {}
    started = asyncio.Event()

    async def _fake_run(mailer, stop_event, **kwargs):
        received.update(kwargs)
        started.set()
        await stop_event.wait()

    async def _noop_async(*_args) -> None:
        return None

    monkeypatch.setattr("main.run_forever", _fake_run)
    monkeypatch.setattr("main.start_scheduler", _noop_async)
    monkeypatch.setattr("main.shutdown_scheduler", _noop_async)
    monkeypatch.setattr("main.warm_up_password_backend", _noop_async)
    monkeypatch.setattr("main.shutdown_password_executor", lambda: None)
    monkeypatch.setattr("main.settings.MAIL_WORKER_POLL_INTERVAL_SECONDS", 7)

    async with lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)

    assert received == {"poll_interval_seconds": 7}


async def test_app_lifespan_startup_failure_hides_original_message(monkeypatch):
    """app 實際掛上的 lifespan 有包遮罩：啟動失敗時交給 uvicorn 的文字不含原例外訊息（#905 B11）。"""
    secret = "A123456789"

    async def _failing_warm_up() -> None:
        raise RuntimeError(f"暖機失敗 id={secret}")

    monkeypatch.setattr("main.warm_up_password_backend", _failing_warm_up)

    incoming = iter([{"type": "lifespan.startup"}])
    sent: list[dict] = []

    async def receive() -> dict:
        return next(incoming)

    async def send(message: dict) -> None:
        sent.append(message)

    with pytest.raises(RuntimeError):
        await app.router.lifespan({"type": "lifespan", "app": app, "state": {}}, receive, send)

    assert sent[-1]["type"] == "lifespan.startup.failed"
    assert secret not in sent[-1]["message"]


async def test_lifespan_starts_and_stops_loop_watchdog(monkeypatch):
    """lifespan 以 settings 的門檻啟用 watchdog，關閉時先停（#905 B16）。"""
    calls: list[tuple] = []

    async def _noop_async(*_args) -> None:
        return None

    async def _fake_run(mailer, stop_event, **kwargs):
        await stop_event.wait()

    def _fake_start(timeout_sec):
        calls.append(("start", timeout_sec))
        return "TASK"

    async def _fake_stop(task):
        calls.append(("stop", task))

    monkeypatch.setattr("main.run_forever", _fake_run)
    monkeypatch.setattr("main.start_scheduler", _noop_async)
    monkeypatch.setattr("main.shutdown_scheduler", _noop_async)
    monkeypatch.setattr("main.warm_up_password_backend", _noop_async)
    monkeypatch.setattr("main.shutdown_password_executor", lambda: None)
    monkeypatch.setattr("main.loop_watchdog.start", _fake_start)
    monkeypatch.setattr("main.loop_watchdog.stop", _fake_stop)
    monkeypatch.setattr("main.settings.EVENT_LOOP_WATCHDOG_SEC", 180.0)

    async with lifespan(app):
        assert calls == [("start", 180.0)]

    assert calls == [("start", 180.0), ("stop", "TASK")]
