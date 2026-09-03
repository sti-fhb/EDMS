"""LIKE 模式跳脫共用工具（L1，unit，無需 DB）。"""

import pytest

from app.core.like_escape import LIKE_ESCAPE_CHAR, contains, escape_like

pytestmark = pytest.mark.unit


def test_escape_wildcards_to_literal():
    # % / _ / \ 皆跳脫為字面（前置反斜線）
    assert escape_like("a%b") == "a\\%b"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("a\\b") == "a\\\\b"


def test_escape_plain_text_unchanged():
    assert escape_like("領血SOP") == "領血SOP"
    assert escape_like("zhang@e.com") == "zhang@e.com"


def test_contains_wraps_with_percent():
    # 外層 % 為萬用（包含比對），內層使用者輸入之 % 已跳脫為字面
    assert contains("50%") == "%50\\%%"
    assert contains("a_b") == "%a\\_b%"


def test_escape_char_is_backslash():
    assert LIKE_ESCAPE_CHAR == "\\"
