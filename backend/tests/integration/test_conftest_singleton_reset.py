"""integration 的單例重置確實接上（#654）。

重置函式本身的正確性（弄髒 → 重置 → 全空）由 `tests/unit/test_conftest_singleton_reset.py` 驗；
本檔只驗**接線**：autouse fixture 真的在每條 integration 測試開始前呼叫了重置。

⚠️ 前提「測試開始前單例是髒的」必須**確定發生**，不能靠「同一 worker 先前恰好有測試弄髒過」——
xdist 下本檔可能是該 worker 的第一條測試，此時單例本來就空，斷言全空恆綠（正是 #654 要消除的
假證據形狀）。故以 module scope 的 fixture 先弄髒：較高 scope 的 fixture 必定早於 function scope
的 `_reset_process_singletons` 建立。
"""

import pytest

from app.core.cooldown import VerifySendCooldown

pytestmark = pytest.mark.integration


def _state(obj) -> dict:
    return obj._last if isinstance(obj, VerifySendCooldown) else obj._hits


@pytest.fixture(scope="module", autouse=True)
def _dirty_before_reset(process_singletons):
    """在重置 fixture 之前把每個單例弄髒。"""
    for obj in process_singletons:
        if isinstance(obj, VerifySendCooldown):
            obj.record("zz-654")
        else:
            obj.try_record("zz-654")
    assert all(_state(obj) for obj in process_singletons), "前提：每個單例都已被弄髒"


def test_每條測試開始前重置確實發生(request, process_singletons):
    """reset 被改成 no-op、autouse 被拿掉、或收集範圍縮成空 → 紅。"""
    assert "_reset_process_singletons" in request.fixturenames
    assert process_singletons, "前提：import main 後應收集到單例"

    assert [obj for obj in process_singletons if _state(obj)] == []
