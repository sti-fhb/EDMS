"""`SCHDM001` KPI 週報排程 handler 本體（`dm/kpi/scheduler.run`）之守門（#700）。

## 為何需要這道守門

`kpi/scheduler.run()` 是 `DP_SCHEDULE.HANDLER_REF` 實際指向的 callable，但它**先前零測試
覆蓋**：既有的 `tests/integration/dm/test_dm_kpi_schedule.py` 直接 `import KpiService` 測
**服務**、用測試自己的 session；`run()` 那層殼——自建 session、`await db.commit()`、記 log
——沒有任何測試執行過（`grep -rn "kpi.scheduler" backend/tests/` 零命中）。

這層 12 行的殼之所以值得測，是因為 `kpi/service.py` 自己標註：

> ⚠️ 本方法與 `_send_unread_reminders` **共用同一個 session 且最後才 commit**（`scheduler.py`）

commit 的位置因此是這支排程的關鍵耦合點，而它**只存在於 wrapper 裡**。漏掉或順序顛倒的後果：

- 排程每週照常執行
- log 照常印出「DM KPI 週報完成：文件 N、週報排入 M、未讀提醒 K 位閱覽者」
- 但 outbox 的列在 session 關閉時整批 rollback ⇒ **週報與未讀提醒一封都沒寄出**
- 沒有任何異常訊號

症狀是「沒收到週報」，而任何人都會先去查範本、收件人、`DM_ADMIN` 角色——不會想到 wrapper
的 commit。**這與 #627 是同一個形狀**：排程唯一的對外訊號與實際產出脫鉤，而那次存活了兩個月。

## 為何用 mock 而非真 DB

要驗的是**殼本身的行為**，不是業務邏輯（後者已有整合測試）。用真 DB 反而驗不到「commit
有沒有被呼叫」——integration 的 fixture 會自己管交易。依 `sti-testing.md`「拿掉真 DB 還驗
得了嗎」的閘門，驗得了 → 寫 unit。

## ⛔ 兩條刻意不做的事

1. **不照抄 `test_dm_reminder_job.py` 的「讀出門檻參數」那條。** 那是 `SCHDM002` 的事；
   KPI **不讀 `DP_PARAM`**——`scheduler.py` 的 docstring 明載 `CRON_EXPR` 是唯一事實來源，
   `DM_WEEKLY_SCHED_DAY_TIME` 已於 #332 移除。硬抄會變成驗 mock 而不是驗程式。
2. **不斷言 mock 的回傳值。** 那種斷言恆真，驗的是 mock 不是程式。
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dm.kpi import scheduler
from app.dm.kpi.service import WeeklyRunResult

pytestmark = pytest.mark.unit


def _fake_session_factory(db):
    """模擬 `AsyncSessionLocal()` 的 async context manager。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), cm


@pytest.fixture
def db():
    return MagicMock(commit=AsyncMock(), close=AsyncMock())


async def test_commit_在_run_weekly_之後被呼叫(db):
    """缺了 `commit`（或順序顛倒）⇒ 週報與未讀提醒整批 rollback，而 log 照報成功。

    `run_weekly` 內部的 `_send_weekly_report` 與 `_send_unread_reminders` **共用同一個
    session**，所以這一個 commit 同時決定兩批信的命運。

    順序由共用的 `calls` 記錄：只斷言「有呼叫 commit」不夠——commit 跑在 `run_weekly`
    之前等於 commit 一個空交易，outbox 的列仍會在 session 關閉時消失。
    """
    calls: list[str] = []

    async def _run_weekly(*_a, **_kw):
        calls.append("run_weekly")
        return WeeklyRunResult(total_docs=1, weekly_queued=1, unread_notified=1)

    async def _commit():
        calls.append("commit")

    db.commit = AsyncMock(side_effect=_commit)
    factory, _cm = _fake_session_factory(db)
    with (
        patch.object(scheduler, "AsyncSessionLocal", factory),
        patch.object(scheduler.KpiService, "run_weekly", AsyncMock(side_effect=_run_weekly)),
    ):
        await scheduler.run()

    assert calls == ["run_weekly", "commit"], f"順序不對：{calls}"


async def test_session_以_async_with_關閉(db):
    """殼的第三個職責：session 要還回去。

    `async with` 漏寫（例如改成 `db = AsyncSessionLocal()`）時，連線不會歸還連線池；
    每週一次、每次洩一條，正式環境要很久才看得出來，而且症狀會長成「DB 連線數滿」
    而不是「排程壞了」。
    """
    factory, cm = _fake_session_factory(db)
    with (
        patch.object(scheduler, "AsyncSessionLocal", factory),
        patch.object(
            scheduler.KpiService,
            "run_weekly",
            AsyncMock(return_value=WeeklyRunResult(total_docs=0, weekly_queued=0, unread_notified=0)),
        ),
    ):
        await scheduler.run()

    cm.__aenter__.assert_awaited_once()
    cm.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    ("docs", "weekly", "unread"),
    [(7, 3, 11), (23, 5, 2)],
)
async def test_log_三個數字各自對應正確欄位(db, caplog, docs, weekly, unread):
    """log 是這支排程**唯一的對外訊號**，數字錯位等於訊號說謊。

    ⚠️ 三個值刻意**互不相同**：全填同一個數的話，`logger.info` 的參數順序寫反也照樣通過。

    ⚠️ 並以 `parametrize` 跑**兩組不同的值**：單一組值無法分辨「正確取欄位」與「把數字寫死」
    ——寫死的話第二組一定紅。
    """
    factory, _cm = _fake_session_factory(db)
    with (
        patch.object(scheduler, "AsyncSessionLocal", factory),
        patch.object(
            scheduler.KpiService,
            "run_weekly",
            AsyncMock(return_value=WeeklyRunResult(total_docs=docs, weekly_queued=weekly, unread_notified=unread)),
        ),
        caplog.at_level(logging.INFO, logger="app.dm.kpi.scheduler"),
    ):
        await scheduler.run()

    assert f"文件 {docs}、週報排入 {weekly}、未讀提醒 {unread} 位閱覽者" in caplog.text, (
        f"log 的三個數字與 WeeklyRunResult 不符：{caplog.text!r}"
    )
