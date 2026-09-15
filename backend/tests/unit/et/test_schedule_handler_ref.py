"""`DP_SCHEDULE.HANDLER_REF` 與 ET handler 的對應（US14 / #325）。

## 這一檔防的是一種不會有人發現的壞掉

`HANDLER_REF` 是存在 DB 的**字串**，排程引擎以 `importlib` 動態解析。改名或搬移
`daily_job` 時，型別檢查、lint、既有測試全部照樣綠——只有排程在每日觸發時解析失敗，
寫一筆 `DP_SCHEDULE_LOG.STATUS='FAILED'` 然後安靜地什麼都不做。

沒有人每天看那張表，所以「到期課程不再自動關閉」會以「沒有任何錯誤訊息」的形式存在
數週。故把 migration 裡那個字串literal 釘在這裡：改名會讓本檔紅，逼使 migration 一起改。
"""

import importlib

import pytest

from app.et.schedules.handlers import daily_job, weekly_job

pytestmark = pytest.mark.unit

#: 與 migration 寫進 `DP_SCHEDULE.HANDLER_REF` 的字串**逐字相同**。
_SCHET001_HANDLER_REF = "app.et.schedules.handlers.weekly_job"
_SCHET002_HANDLER_REF = "app.et.schedules.handlers.daily_job"

#: 排程引擎的動態 import 白名單（`dp/schedules/scheduler._ALLOWED_HANDLER_PREFIXES`）。
_ALLOWED_PREFIXES = ("app.dp.", "app.et.", "app.dm.")


def _resolve(handler_ref: str):
    """比照引擎的解析方式：dotted path → callable。"""
    module_path, _, attr = handler_ref.rpartition(".")
    return getattr(importlib.import_module(module_path), attr)


@pytest.mark.parametrize(
    ("handler_ref", "expected"),
    [(_SCHET001_HANDLER_REF, weekly_job), (_SCHET002_HANDLER_REF, daily_job)],
    ids=["SCHET001", "SCHET002"],
)
class TestHandlerRef:
    def test_解析得到的正是該handler(self, handler_ref: str, expected) -> None:
        assert _resolve(handler_ref) is expected

    def test_在引擎的白名單命名空間內(self, handler_ref: str, expected) -> None:
        """白名單之外的 `HANDLER_REF` 會被引擎拒載（CWE-470 縱深防禦）。"""
        assert handler_ref.startswith(_ALLOWED_PREFIXES)

    def test_是async無參callable(self, handler_ref: str, expected) -> None:
        """引擎以 `await handler()` 呼叫——帶參數或非 coroutine 會在執行當下才爆。"""
        import inspect

        assert inspect.iscoroutinefunction(expected)
        assert not inspect.signature(expected).parameters
