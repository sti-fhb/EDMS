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

    async with lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)
        assert started.is_set()
    # 離開 context 後 _fake_run 已優雅返回（未逾時強制取消）
