"""通知發送服務 SRVDP002（T018）純函式單元測試：渲染 / CHANNEL 判定（不連 DB）。"""

import pytest

from app.dp.notify.service import _channel_allows_email, _render

pytestmark = pytest.mark.unit


def test_render_substitutes_params():
    """範本佔位以 params 代入。"""
    assert _render("Hi {name}, code={code}", {"name": "小明", "code": "123"}) == "Hi 小明, code=123"


def test_render_no_placeholder_returns_as_is():
    """無佔位的範本原樣回傳。"""
    assert _render("純文字內容", {"unused": "x"}) == "純文字內容"


def test_render_missing_var_raises_keyerror():
    """範本需要的變數 params 未提供 → 拋 KeyError（呼叫端據以標該列 FAILED）。"""
    with pytest.raises(KeyError):
        _render("Hi {name}", {"other": "x"})


def test_render_unbalanced_brace_raises_valueerror():
    """範本含未閉合大括號 → 拋 ValueError（呼叫端據以標該列 FAILED，不外拋）。"""
    with pytest.raises(ValueError, match="."):
        _render("hello {name", {"name": "x"})


def test_render_blocks_attribute_access():
    """封鎖屬性存取（防 {x.__class__...__globals__} 讀機密）→ ValueError。"""
    with pytest.raises(ValueError, match="具名變數"):
        _render("{x.__class__}", {"x": "y"})


def test_render_blocks_index_and_positional():
    """封鎖索引 / 位置佔位 → ValueError。"""
    with pytest.raises(ValueError, match="具名變數"):
        _render("{0}", {"0": "y"})


def test_render_blocks_format_spec():
    """封鎖格式規格（防 {v:>200000000} OOM）→ ValueError。"""
    with pytest.raises(ValueError, match="格式規格"):
        _render("{name:>100}", {"name": "x"})


def test_render_coerces_non_str_value():
    """值非 str 亦安全 str() 代入（無屬性存取路徑）。"""
    assert _render("n={n}", {"n": 123}) == "n=123"


@pytest.mark.parametrize(
    ("channel", "expected"),
    [("EMAIL", True), ("BOTH", True), ("MSG", False)],
)
def test_channel_allows_email(channel, expected):
    """僅 EMAIL / BOTH 寄 Email；MSG（純站內）不寄。"""
    assert _channel_allows_email(channel) is expected
