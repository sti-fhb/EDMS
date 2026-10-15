"""`SCHDM002` 催辦排程 handler 本體（`dm/review/reminder.run`）之守門（#627）。

## 為何需要這道守門

`reminder.run()` 是 `DP_SCHEDULE.HANDLER_REF` 實際指向的 callable，但它**先前零測試覆蓋**：
既有的催辦整合測試全都直接呼叫 `ReviewCenterService.scan_overdue_and_remind`，並用測試自己的
session；`run()` 的那層殼——自建 session、讀參數、**`await db.commit()`**、記 log——沒有任何
測試執行過。

這層殼漏掉 `commit` 的後果，與 #627 本身是**同一個形狀**：排程每天執行、log 照常印出
「已排入寄信 N 筆」，而 outbox 的列在 session 關閉時整批 rollback ⇒ 一封信都沒寄出，
且沒有任何異常訊號。#627 的教訓就是這種「唯一的對外訊號在說謊」能存活兩個月無人察覺。

## 為何用 mock 而非真 DB

要驗的是**殼本身的行為**，不是業務邏輯（後者已有整合測試）：

- 參數有被讀出來並傳給 service（不是用寫死的門檻）
- `commit` 有被呼叫，且**在 scan 之後**——順序顛倒等於 commit 空交易
- session 有被關閉（`async with`）

這些都不需要真 DB，用真 DB 反而驗不到「commit 有沒有被呼叫」（整合測試的 fixture 會自己
管交易）。⚠️ 刻意**不**斷言 mock 的回傳值——那種斷言恆真，驗的是 mock 不是程式。
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dm.review import reminder

pytestmark = pytest.mark.unit


def _fake_session_factory(db):
    """模擬 `AsyncSessionLocal()` 的 async context manager。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.fixture
def db():
    return MagicMock(commit=AsyncMock(), close=AsyncMock())


async def test_讀出門檻參數並傳給_service(db):
    """門檻來自 `DP_PARAM`，不得寫死——管理者在 DP03 調整後必須當天生效。"""
    scan = AsyncMock(return_value=3)
    with (
        patch.object(reminder, "AsyncSessionLocal", _fake_session_factory(db)),
        patch.object(reminder.ParamService, "get_int_param", AsyncMock(return_value=11)),
        patch.object(reminder.ReviewCenterService, "scan_overdue_and_remind", scan),
    ):
        await reminder.run()

    scan.assert_awaited_once()
    assert scan.await_args.kwargs["threshold_days"] == 11, "門檻沒有從參數傳進去——改 DP03 將不會生效"


async def test_commit_在_scan_之後被呼叫(db):
    """缺了 `commit`（或順序顛倒）⇒ outbox 整批 rollback，而 log 照報成功。

    這正是 #627 的形狀：排程唯一的對外訊號與實際產出脫鉤。順序由共用的 `calls` 記錄，
    只斷言「有呼叫 commit」是不夠的——commit 跑在 scan 之前等於 commit 一個空交易。
    """
    calls: list[str] = []

    async def _scan(*_a, **_kw):
        calls.append("scan")
        return 2

    async def _commit():
        calls.append("commit")

    db.commit = AsyncMock(side_effect=_commit)
    with (
        patch.object(reminder, "AsyncSessionLocal", _fake_session_factory(db)),
        patch.object(reminder.ParamService, "get_int_param", AsyncMock(return_value=7)),
        patch.object(reminder.ReviewCenterService, "scan_overdue_and_remind", AsyncMock(side_effect=_scan)),
    ):
        await reminder.run()

    assert calls == ["scan", "commit"], f"scan 與 commit 的順序不對：{calls}"


async def test_log_印出的是實際排入寄信的筆數(db, caplog):
    """#627：`count` 現在只數真的進 outbox 的，log 文案與數字都要跟著它。

    先前 `count` 是「掃到的筆數」，於是範本不寄信的那兩個月每天照報「催辦 N 筆」。
    這條釘住「log 的數字＝`scan_overdue_and_remind` 的回傳值」這層對應關係。
    """
    with (
        patch.object(reminder, "AsyncSessionLocal", _fake_session_factory(db)),
        patch.object(reminder.ParamService, "get_int_param", AsyncMock(return_value=7)),
        patch.object(reminder.ReviewCenterService, "scan_overdue_and_remind", AsyncMock(return_value=5)),
        caplog.at_level(logging.INFO, logger="app.dm.review.reminder"),
    ):
        await reminder.run()

    assert "已排入寄信 5 筆" in caplog.text, "log 必須印出實際排入的筆數"
    # 反向錨點：舊文案把「掃到幾筆」說成「催辦幾筆」，那正是 #627 讓問題隱形兩個月的原因
    assert "催辦 5 筆" not in caplog.text
