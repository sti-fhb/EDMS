"""ET03 學員學習狀況追蹤之純業務規則（US9 / #322）。

完課三態沿用 `enrollment/rules.derive_completion_status`（已有測試於
`test_enrollment_rules.py`），本檔只驗本 issue 新增的判定。
"""

import pytest

from app.et.tracking.rules import can_reset_retry

pytestmark = pytest.mark.unit


class TestCanResetRetry:
    """重置重考次數的可用條件（AC 6 / FR-ET-US9-06）。

    ## ⚠️ 「次數用盡」是 `used > max_retry`，不是 `used >= max_retry`

    總可作答次數 = **`MAX_RETRY + 1`**（`attempt/rules.can_start_attempt` 的
    docstring 明訂：`MAX_RETRY = 0` 是「只能作答 1 次」而非「不能作答」）。

    寫成 `used >= max_retry` 會讓學員**還剩最後一次**時，教師就看到一顆可點的重置
    按鈕——按下去等於白送一輪配額，而畫面上完全看不出哪裡不對。

    四種「不可重置」的理由各自不同，混在一起只寫 happy path 會讓其中三種悄悄失效。
    """

    def test_次數用盡且未及格可重置(self) -> None:
        """唯一可重置的情形——重考次數對他已經沒有意義了，只有教師能解。

        `max_retry=3` 的總配額是 4 次，故 `used=4` 才是用盡。
        """
        assert can_reset_retry(used=4, max_retry=3, is_passed=False, has_attempt=True) is True

    def test_還剩最後一次不可重置(self) -> None:
        """`used=3` / `max_retry=3` 時**還能再作答一次**（總配額 4 次）。

        這是 `>=` 與 `>` 之差唯一看得出來的地方，也是最容易寫錯的一格。
        """
        assert can_reset_retry(used=3, max_retry=3, is_passed=False, has_attempt=True) is False

    def test_還有多次不可重置(self) -> None:
        assert can_reset_retry(used=1, max_retry=3, is_passed=False, has_attempt=True) is False

    def test_已及格不可重置(self) -> None:
        """及格後重置沒有語意——他已經通過了，重考只會有機會把成績弄低。

        ⚠️ 與「次數用盡」是**獨立**條件：最後一次才及格的學員同時滿足兩者，仍不可重置。
        """
        assert can_reset_retry(used=4, max_retry=3, is_passed=True, has_attempt=True) is False

    def test_未作答不可重置(self) -> None:
        """沒有任何 attempt 時「重置」無從談起——他的配額原本就是滿的。"""
        assert can_reset_retry(used=0, max_retry=3, is_passed=False, has_attempt=False) is False

    def test_只能作答一次者用完後可重置(self) -> None:
        """`max_retry=0` ＝ 只能作答 1 次（**不是**不能作答、也不是不限次數）。

        用掉那一次（`used=1`）即為用盡。把 `0` 誤讀成「不限次數」會讓這類測驗的學員
        永遠等不到重置；誤讀成「不能作答」則會讓未作答者也冒出可點的按鈕。
        """
        assert can_reset_retry(used=1, max_retry=0, is_passed=False, has_attempt=True) is True
        assert can_reset_retry(used=0, max_retry=0, is_passed=False, has_attempt=False) is False

    def test_已用次數超過上限仍可重置(self) -> None:
        """資料異常時取寬鬆側——`used` 遠超上限不該讓按鈕消失。

        成因可能是教師事後調小了 `MAX_RETRY`（既有功能允許）。此時學員的處境與「剛好
        用盡」完全相同，卻因為一個嚴格的等號比對而拿不到救濟。
        """
        assert can_reset_retry(used=10, max_retry=3, is_passed=False, has_attempt=True) is True
