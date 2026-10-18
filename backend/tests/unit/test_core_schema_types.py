"""`core/schema_types.py` 兩條單行 pattern 的守門（#697）。

## 為何需要這兩條測試

`SAFE_SINGLE_LINE_PATTERN`（`+`）與 `SAFE_SINGLE_LINE_OR_EMPTY_PATTERN`（`*`）的差別**只該是
空字串**。後者於 #697 新增，供 multipart 的 `Form()` 欄位使用——DM 編輯器的存草稿路徑刻意
允許空名稱 / 空版號，`+` 版會讓那條路徑一律 422。

真正促成本檔的是初版的一個缺陷：`*` 版的 `\\u2028` / `\\u2029` 被寫成了**字面字元**而非跳脫
序列。行為當時仍正確（字面 U+2028 放進字元類別的效果與跳脫相同），所以任何功能測試都抓不到；
但在編輯器與 diff 裡那兩個字元看起來就是空白，下一個人「順手清掉多餘空白」就會靜默移除
U+2028 / U+2029 的防線——而那正是 `SafeNameStr` docstring 花了一整段解釋為何非擋不可的字元。

⇒ 字元類別現已抽成 `_UNSAFE_LINE_CHARS` 由兩條共用（防分岔），並由 `isascii()` 擋住隱形字元。
"""

import re
from pathlib import Path

import pytest
from pydantic import Field, ValidationError, create_model

from app.core.schema_types import (
    SAFE_MULTILINE_PATTERN,
    SAFE_SINGLE_LINE_OR_EMPTY_PATTERN,
    SAFE_SINGLE_LINE_PATTERN,
)

pytestmark = pytest.mark.unit

#: 必須被兩條 pattern 擋下的字元。取自 `str.splitlines()` 的切點（`SafeNameStr` docstring 的推導），
#: 外加 C1 全段的代表值。
_MUST_REJECT = [
    ("NUL", "\x00"),
    ("LF", "\n"),
    ("CR", "\r"),
    ("VT", "\x0b"),
    ("FF", "\x0c"),
    ("FS", "\x1c"),
    ("GS", "\x1d"),
    ("RS", "\x1e"),
    ("DEL", "\x7f"),
    ("NEL U+0085", "\x85"),
    ("C1 U+009F", "\x9f"),
    ("LINE SEPARATOR U+2028", "\u2028"),
    ("PARAGRAPH SEPARATOR U+2029", "\u2029"),
]


def test_pattern_原始碼不得含隱形字元():
    """🔴 `\\u2028` 寫成字面字元時，原始碼裡看起來就是空白——這條是唯一抓得到的方式。

    功能測試抓不到：字面 U+2028 與跳脫序列在字元類別裡等效，兩種寫法的**行為完全相同**。
    會出事的是下一次有人編輯這個檔案。
    """
    assert SAFE_SINGLE_LINE_PATTERN.isascii(), "pattern 含非 ASCII 字元（很可能是字面 U+2028 / U+2029）"
    assert SAFE_SINGLE_LINE_OR_EMPTY_PATTERN.isascii(), "pattern 含非 ASCII 字元（很可能是字面 U+2028 / U+2029）"
    assert SAFE_MULTILINE_PATTERN.isascii(), "pattern 含非 ASCII 字元（很可能是字面 U+2028 / U+2029）"

    # ⚠️ 本檔自己也曾犯同一個錯（`_MUST_REJECT` 裡寫成字面字元）——守門只盯 `schema_types.py`
    # 的常數，盯不到測試檔，故這裡自檢一次。
    src = Path(__file__).read_text(encoding="utf-8")
    assert not [c for c in src if c in "\u2028\u2029"], "本測試檔含字面 U+2028 / U+2029——請改寫成跳脫序列"


@pytest.mark.parametrize(("label", "char"), _MUST_REJECT)
def test_兩條_pattern_擋下同一組字元(label, char):
    """兩條只該差在空字串；字元集分岔會讓其中一條悄悄變寬。"""
    probe = f"正常{char}文字"
    assert re.match(SAFE_SINGLE_LINE_PATTERN, probe) is None, f"`+` 版未擋下 {label}"
    assert re.match(SAFE_SINGLE_LINE_OR_EMPTY_PATTERN, probe) is None, f"`*` 版未擋下 {label}"


def test_兩條_pattern_的唯一差異是空字串():
    """正向錨點 + 差異點各一。只驗「都擋 X」的話，兩條都寫成 `^$` 也會全過。"""
    assert re.match(SAFE_SINGLE_LINE_PATTERN, "正常的文件名稱") is not None
    assert re.match(SAFE_SINGLE_LINE_OR_EMPTY_PATTERN, "正常的文件名稱") is not None

    assert re.match(SAFE_SINGLE_LINE_PATTERN, "") is None, "`+` 版應拒空字串（姓名等必填欄位）"
    assert re.match(SAFE_SINGLE_LINE_OR_EMPTY_PATTERN, "") is not None, "`*` 版應放行空字串（存草稿）"


@pytest.mark.parametrize(("label", "char"), _MUST_REJECT)
def test_production_引擎下也擋下同一組字元(label, char):
    """🔴 上面那幾條走 Python 的 `re`，**production 走的是 Pydantic 的 rust-regex**。

    兩者的 `$` 語意不同：Python 的 `$` 也匹配「結尾換行之前」，Rust 的只匹配 haystack 結尾
    （分岔點見 `test_尾端換行是兩個引擎的已知分岔點`）。

    目前不構成漏洞（rust-regex 是較嚴格的那邊，且探針把字元放在中間、碰不到分岔），
    但「兩條 pattern 擋下同一組字元」這個結論若只由 `re` 背書，證據基礎就是錯的引擎。
    本條讓守門與 production 走同一條路。
    """
    model = create_model("_Probe", v=(str, Field(pattern=SAFE_SINGLE_LINE_PATTERN)))
    with pytest.raises(ValidationError, match="String should match pattern"):
        model(v=f"正常{char}文字")
    # 正向錨點：證明這個 model 真的驗得過正常值（否則「每個字元都 raise」可能是 model 壞了）
    assert model(v="正常的文件名稱").v == "正常的文件名稱", label


def test_尾端換行是兩個引擎的已知分岔點():
    """把分岔本身釘住——日後若 Pydantic 換引擎或改語意，這條會紅並指向上面那條的前提。"""
    import re as _re

    assert _re.match(SAFE_SINGLE_LINE_PATTERN, "abc\n") is not None, "Python re 的 $ 允許結尾換行"
    model = create_model("_Probe2", v=(str, Field(pattern=SAFE_SINGLE_LINE_PATTERN)))
    with pytest.raises(ValidationError):
        model(v="abc\n")
