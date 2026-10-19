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

### ⚠️ 本檔守不住的另一半

上述因果鏈成立，靠的是**兩件事**：①wrapper 有 commit（本檔守住）②整條鏈上**沒有別人**
commit——`dp/notify/repository.add_logs` 只 `flush()`、`NotifyService.send_email` 明載「於
呼叫方交易內執行（同一 db session、只 flush）」。

本檔**只守得住第①件**。若日後有人在 `add_logs` 或 `run_weekly` 裡加了 `commit()`，
「信件之所以持久化是因為 wrapper commit」這條性質就變形了，而這 4 條測試**仍然全綠**
——那正是本檔開頭引用的 #627 形狀。第②件目前只由那兩處的 docstring 約定，沒有測試守著。

## 為何用「會記事件的 fake」而不是 mock 的 `assert_awaited`

初版用 `MagicMock` + `cm.__aexit__.assert_awaited_once()`。code review 指出那條**沒有被驗證
過**：注入「拿掉 `async with`」時 4 條全紅，但訊息是 `TypeError`（`db` 變成 factory 的
`MagicMock`、`await db.commit()` 直接炸），那兩行斷言根本沒機會執行——**紅得對，但不是因為
它偵測到**。

改成手寫的 async context manager，把 `enter` / `exit` 與 `run_weekly` / `commit` 記進**同一條
`calls`**，斷言完整序列。這樣多守住一件原本漏掉的事：**commit 必須發生在 session 之內**
（有人把 `await db.commit()` 搬出 `with` 區塊，就是對已關閉的 session commit，舊版抓不到）。

## 為何用 mock 而非真 DB

要驗的是**殼本身的行為**（session 生命週期、commit 位置、log 欄位），不是業務邏輯（後者已有
整合測試）。用真 DB 反而驗不到「commit 有沒有被呼叫」——integration 的 fixture 會自己管交易。
依 `sti-testing.md`「拿掉真 DB 還驗得了嗎」的閘門，驗得了 → 寫 unit。

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


class _RecordingSession:
    """會把生命週期事件記進共用 `calls` 的假 session（兼 async context manager）。

    刻意不用 `MagicMock`：mock 的 `assert_awaited` 只能證明「被呼叫過」，證明不了**順序**，
    而本檔要守的正是 commit 相對於 session 開關的位置。
    """

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def __aenter__(self) -> "_RecordingSession":
        self._calls.append("enter")
        return self

    async def __aexit__(self, *_exc) -> bool:
        self._calls.append("exit")
        return False  # 不吞例外

    async def commit(self) -> None:
        self._calls.append("commit")


def _session_factory(calls: list[str]) -> MagicMock:
    """模擬 `AsyncSessionLocal`——呼叫它回傳一個 `_RecordingSession`。

    ⚠️ 每次呼叫回**同一個**實例。目前 `run()` 只開一個 session 所以沒問題；日後若改成開兩個，
    兩個 session 的事件會記進同一條 `calls`、看起來像一個交錯的 session，順序斷言可能**靜默
    讀錯**。屆時要改成每次 `return` 新實例並分開記錄。
    """
    return MagicMock(return_value=_RecordingSession(calls))


def _result(docs: int = 1, weekly: int = 1, unread: int = 1) -> WeeklyRunResult:
    return WeeklyRunResult(total_docs=docs, weekly_queued=weekly, unread_notified=unread)


async def test_session_開關與_commit_的完整順序():
    """殼的三個職責一次釘住：開 session → 跑批次 → commit → 關 session。

    這條同時守住三件事，少任何一件都會紅：

    1. **commit 有被呼叫**——漏掉的話 outbox 的列在 session 關閉時整批 rollback，
       而 log 照報成功。
    2. **commit 在 `run_weekly` 之後**——跑在前面等於 commit 一個空交易。
    3. **commit 在 session 之內**（`exit` 必須是最後一個）——搬出 `with` 區塊就是對已關閉的
       session commit。初版只斷言「`__aexit__` 被呼叫過一次」，抓不到這一項。
    """
    calls: list[str] = []

    async def _run_weekly(*_a, **_kw):
        calls.append("run_weekly")
        return _result()

    with (
        patch.object(scheduler, "AsyncSessionLocal", _session_factory(calls)),
        patch.object(scheduler.KpiService, "run_weekly", AsyncMock(side_effect=_run_weekly)),
    ):
        await scheduler.run()

    assert calls == ["enter", "run_weekly", "commit", "exit"], f"生命週期順序不對：{calls}"


async def test_批次拋例外時不得_commit_但仍要關閉_session():
    """`async with` 的價值主要在**失敗路徑**。

    `run_weekly` 中途炸掉時：
    - **不得 commit**——否則半套的 outbox（例如週報已排入、未讀提醒還沒）會被寫進去，
      而下一次執行不知道上次做到哪裡，收件人會收到重複的週報。
    - **session 仍要關閉**——否則連線不歸還連線池，每週洩一條。

    這條也守住「有人把 commit 改進 `try/finally`」的退化：那會讓失敗路徑也 commit，
    而現有的順序測試（成功路徑）完全抓不到。
    """
    calls: list[str] = []

    async def _boom(*_a, **_kw):
        calls.append("run_weekly")
        raise RuntimeError("KPI 計算中途失敗")

    with (
        patch.object(scheduler, "AsyncSessionLocal", _session_factory(calls)),
        patch.object(scheduler.KpiService, "run_weekly", AsyncMock(side_effect=_boom)),
        pytest.raises(RuntimeError, match="KPI 計算中途失敗"),
    ):
        await scheduler.run()

    assert "commit" not in calls, f"失敗路徑不該 commit：{calls}"
    assert calls == ["enter", "run_weekly", "exit"], f"失敗路徑的生命週期不對：{calls}"


@pytest.mark.parametrize(
    ("docs", "weekly", "unread"),
    [(7, 3, 11), (23, 5, 2)],
)
async def test_log_三個數字各自對應正確欄位(caplog, docs, weekly, unread):
    """log 是這支排程**唯一的對外訊號**，數字錯位等於訊號說謊。

    ⚠️ 三個值刻意**互不相同**：全填同一個數的話，`logger.info` 的參數順序寫反也照樣通過。

    ⚠️ 並以 `parametrize` 跑**兩組不同的值**：單一組值無法分辨「正確取欄位」與「把數字寫死」
    ——實測把數字寫死成第一組時，**只有第二組會紅**。
    """
    calls: list[str] = []
    with (
        patch.object(scheduler, "AsyncSessionLocal", _session_factory(calls)),
        patch.object(
            scheduler.KpiService,
            "run_weekly",
            AsyncMock(return_value=_result(docs, weekly, unread)),
        ),
        caplog.at_level(logging.INFO, logger="app.dm.kpi.scheduler"),
    ):
        await scheduler.run()

    assert f"文件 {docs}、週報排入 {weekly}、未讀提醒 {unread} 位閱覽者" in caplog.text, (
        f"log 的三個數字與 WeeklyRunResult 不符：{caplog.text!r}"
    )
