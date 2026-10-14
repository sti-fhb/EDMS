"""每日重建上限的值域夾回（#234）。

為什麼守門在**讀取端**而不是 `param_rules.py` 的 `IntRule`：

該參數為 `EDIT_SCOPE='HIDDEN'`，而 `params/service.py` 的 `is_editable_scope` 403 擋在
值域檢核**之前** —— `IntRule` 對它永遠走不到，加了就是為不存在的 code path 寫防禦
（違反 `sti-coding-style`「不為不存在的情境寫防禦碼」）。真正走得到的修改路徑是
**IT 直接下 SQL**，而 `ParamService.get_int_param` 對整數不設界（只有非整數才回 default）。

⚠️ 本檔由 2026-10-14 code review MEDIUM-3 補入：原本只有一條整合測試驗**下界**，
而 docstring 卻寫「兩端都要夾」——拿掉 `min(high, raw)` 後設 99999 會靜默關掉整道防護，
所有測試仍全綠。那是「測試名稱宣稱涵蓋的範圍大於它實際驗的」那一類假證據。
"""

import pytest

from app.dp.user import router as auth_router

pytestmark = pytest.mark.unit


@pytest.fixture
def stored(monkeypatch):
    """替換參數讀取，直接決定 DB 裡存的是什麼值。"""

    def _set(value: int) -> None:
        async def _fake(_db, _param_id, _key, _default):
            return value

        monkeypatch.setattr(auth_router._params, "get_int_param", _fake)

    return _set


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (99999, 10),  # 設大＝靜默關掉防護：占用時間回到趨近全天
        (11, 10),  # 剛好越界
        (10, 10),  # 上界本身不夾
        (5, 5),  # 預設值原樣通過
        (1, 1),  # 下界本身不夾
        (0, 1),  # 設 0＝任何人都註冊不了
        (-3, 1),  # 負值同理
    ],
)
async def test_上限值夾回合理範圍(stored, value: int, expected: int) -> None:
    stored(value)
    assert await auth_router._overwrite_max(None) == expected


async def test_超界時留下_warning(stored, caplog) -> None:
    """扣下動作必留痕：靜默夾回會讓「我明明設了 99999」與「防護沒生效」對不起來。

    配一條正向對照（界內不得噪音），否則「有 log」這件事會在每次正常讀取時都成立，
    等於把 log 變成雜訊、沒有人會再看它。
    """
    import logging

    stored(99999)
    with caplog.at_level(logging.WARNING):
        assert await auth_router._overwrite_max(None) == 10
    assert "99999" in caplog.text

    caplog.clear()
    stored(5)
    with caplog.at_level(logging.WARNING):
        assert await auth_router._overwrite_max(None) == 5
    assert caplog.text == "", "界內不得留 warning（否則 log 成為雜訊）"
