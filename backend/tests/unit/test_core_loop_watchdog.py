"""event loop 卡住時自動結束程式、交給容器重啟（#905 B16）。

#896 的健康檢查只把容器標成 unhealthy，Docker 非 swarm 模式不會因此重啟；autoheal 之類的容器要掛
Docker socket（等同主機 root），這台 VM 同時跑血庫系統，不划算。改在程式內用 `faulthandler` 的計時器：
event loop 每隔幾秒重設一次，卡住超過門檻就印出所有 thread 的堆疊、以結束碼 1 結束，由
`restart: unless-stopped` 重新啟動。
"""

import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.core import loop_watchdog

pytestmark = pytest.mark.unit

_BACKEND = Path(__file__).resolve().parents[2]


def test_卡住超過門檻時印出堆疊並以結束碼_1_結束():
    """實際起一個 event loop、啟用 watchdog 後用同步的 sleep 卡住 loop：程式要自己結束，不能一直掛著。

    `faulthandler` 的計時器跑在獨立的 C thread、不需要 GIL，Python 卡在死迴圈時照樣觸發——
    這正是選它而不是自己開一條 Python thread 的理由。
    """
    script = textwrap.dedent(
        """
        import asyncio, time
        from app.core import loop_watchdog

        async def main():
            task = loop_watchdog.start(1)
            await asyncio.sleep(0.2)
            time.sleep(10)  # 卡住 event loop：重設計時器的那個 task 不會再被排到
            print("沒有被結束")

        asyncio.run(main())
        """
    )
    result = subprocess.run(  # noqa: S603 — 固定參數，執行本測試自己的腳本
        [sys.executable, "-c", script],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        timeout=8,
    )

    assert result.returncode == 1
    assert "沒有被結束" not in result.stdout
    assert "Timeout (0:00:01)!" in result.stderr, result.stderr
    assert "in main" in result.stderr, "要印出卡在哪個函式"


def test_沒有卡住時不會結束():
    """正常運作時計時器一直被重設，門檻過了也不會觸發。"""
    script = textwrap.dedent(
        """
        import asyncio
        from app.core import loop_watchdog

        async def main():
            task = loop_watchdog.start(3)
            await asyncio.sleep(6)  # 超過門檻，但 loop 沒卡住（門檻放寬到 3 秒：機器忙時子行程被餓死也不至於誤殺）
            await loop_watchdog.stop(task)
            print("正常結束")

        asyncio.run(main())
        """
    )
    result = subprocess.run(  # noqa: S603 — 固定參數，執行本測試自己的腳本
        [sys.executable, "-c", script],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "正常結束" in result.stdout


def test_門檻為_0_時不啟用():
    assert loop_watchdog.start(0) is None


async def test_停止後計時器取消(monkeypatch):
    """關閉流程可能超過門檻（等發信 worker 收斂最多 30 秒等），停止 watchdog 時要取消計時器。"""
    calls: list[str] = []
    monkeypatch.setattr(loop_watchdog.faulthandler, "dump_traceback_later", lambda *a, **k: calls.append("arm"))
    monkeypatch.setattr(loop_watchdog.faulthandler, "cancel_dump_traceback_later", lambda: calls.append("cancel"))

    task = loop_watchdog.start(120)
    await asyncio.sleep(0)
    await loop_watchdog.stop(task)

    assert calls[0] == "arm"
    assert calls[-1] == "cancel"


async def test_計時器以_exit_True_設定(monkeypatch):
    """只印堆疊不結束的話，卡住的程式照樣卡著——要 `exit=True` 才會交給容器重啟。"""
    seen: list[tuple] = []
    monkeypatch.setattr(loop_watchdog.faulthandler, "dump_traceback_later", lambda *a, **k: seen.append((a, k)))
    monkeypatch.setattr(loop_watchdog.faulthandler, "cancel_dump_traceback_later", lambda: None)

    task = loop_watchdog.start(120)
    await asyncio.sleep(0)
    await loop_watchdog.stop(task)

    args, kwargs = seen[0]
    assert args[0] == 120
    assert kwargs.get("exit") is True


async def test_task_意外結束時記錯誤且_stop_不往外拋(monkeypatch, caplog):
    """計時器設定失敗（如門檻溢位）時 task 會死掉：要立刻記 ERROR（否則 watchdog 靜默失效），
    `stop()` 也不能把例外拋給 lifespan——它是關閉流程的第一行，一拋後面等發信 worker 收斂等步驟全被跳過。"""
    import logging

    def _boom(*_a, **_k):
        raise OverflowError("timeout value is too large")

    monkeypatch.setattr(loop_watchdog.faulthandler, "dump_traceback_later", _boom)
    monkeypatch.setattr(loop_watchdog.faulthandler, "cancel_dump_traceback_later", lambda: None)

    with caplog.at_level(logging.ERROR, logger="app.core.loop_watchdog"):
        task = loop_watchdog.start(120)
        await asyncio.sleep(0.05)
        await loop_watchdog.stop(task)  # 不拋

    assert any("watchdog" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)
