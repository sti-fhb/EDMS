"""受訓對象配對的純函式（#538）：編解碼、顯示文字。

匹配條件（`matched_course_users`）需要真 DB，在 `tests/integration/et/test_et_tag_invite.py`。
"""

import pytest

from app.et.catalog.pair import decode_pair, encode_pair, pair_label

pytestmark = pytest.mark.unit


class TestEncodeDecode:
    @pytest.mark.parametrize(("unit", "role"), [(12, 5), (None, 5)])
    def test_編碼後可解回(self, unit, role) -> None:
        assert decode_pair(encode_pair(unit, role)) == (unit, role)

    def test_單位未指定編為冒號開頭(self) -> None:
        """DP02 前端以同一格式解析（與 DM 相同）。"""
        assert encode_pair(None, 5) == ":5"

    @pytest.mark.parametrize(
        "bad",
        [
            "5",  # 少了冒號——#538 之前的舊格式
            "12:",  # 職位必填
            ":",
            "",
            "a:5",
            "12:b",
            "-1:5",
            "0:5",
            "12:0",
            ":²",  # isdigit 為 True、int() 會拋——必須用 isdecimal
            "①:5",
            ":" + "9" * 20,  # 超出 BIGINT
            ":" + "9" * 5000,  # 超過 int() 的 4300 位上限——長度須先擋，否則 ValueError → 500
        ],
        # 測試 id 截短：否則 5000 位數字整串印進 CI 輸出
        ids=lambda v: v if len(v) <= 24 else f"{v[:8]}…({len(v)} 字元)",
    )
    def test_不合法輸入回_None_不拋例外(self, bad) -> None:
        assert decode_pair(bad) is None


class TestLabel:
    @pytest.mark.parametrize(
        ("unit_name", "unit_is_all", "role_name", "expected"),
        [
            ("全單位", True, "全體", "全體"),
            ("全單位", True, "護理師", "護理師"),
            ("國防醫學院三軍總醫院", False, "護理師", "國防醫學院三軍總醫院 + 護理師"),
            ("國防醫學院三軍總醫院", False, "全體", "國防醫學院三軍總醫院 + 全體"),
        ],
    )
    def test_全單位省略其餘成對顯示(self, unit_name, unit_is_all, role_name, expected) -> None:
        assert pair_label(unit_name=unit_name, unit_is_all=unit_is_all, role_name=role_name) == expected

    def test_判定看旗標不看名稱(self) -> None:
        """名字叫「全單位」但不是通用值的單位，照樣成對顯示——與匹配的判定依據一致。"""
        assert pair_label(unit_name="全單位", unit_is_all=False, role_name="護理師") == "全單位 + 護理師"
