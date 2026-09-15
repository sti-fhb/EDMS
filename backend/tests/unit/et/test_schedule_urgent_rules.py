"""加急提醒之門檻判定（T148 / US14 / #325）。

加急提醒的判定有三個互相獨立的閘，任何一個漏掉都不會有錯誤訊息，只會是「信多寄了」
或「信沒寄」——兩者都得靠實際收信才會發現，故全部以 unit 釘住。

## 為何「已到期」也不寄

同一次 SCHET002 執行內，到期關閉排在加急提醒**之前**。若不擋掉已到期者，剛被關掉的
課程會在同一次執行中收到一封「即將截止」——而它已經截止了。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.et.schedules.rules import needs_urgent_remind

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


def _ends_in(**delta) -> datetime:
    return _NOW + timedelta(**delta)


class TestNeedsUrgentRemind:
    def test_進入窗口且未寄過則寄(self) -> None:
        assert needs_urgent_remind(open_end_at=_ends_in(days=2), urgent_days=3, already_sent=False, now=_NOW) is True

    def test_剛好等於門檻仍寄(self) -> None:
        """「訖止前 3 天」含第 3 天當下——邊界排除會讓剛好整數天的課程整批漏寄。"""
        assert needs_urgent_remind(open_end_at=_ends_in(days=3), urgent_days=3, already_sent=False, now=_NOW) is True

    def test_尚未進入窗口不寄(self) -> None:
        assert (
            needs_urgent_remind(open_end_at=_ends_in(days=3, seconds=1), urgent_days=3, already_sent=False, now=_NOW)
            is False
        )

    def test_已寄過不重寄(self) -> None:
        assert needs_urgent_remind(open_end_at=_ends_in(days=1), urgent_days=3, already_sent=True, now=_NOW) is False

    def test_已到期不寄(self) -> None:
        """已逾訖止者由同一次執行的「到期關閉」處理，不再催「即將截止」。"""
        assert needs_urgent_remind(open_end_at=_ends_in(days=-1), urgent_days=3, already_sent=False, now=_NOW) is False

    def test_訖止當下不寄(self) -> None:
        assert needs_urgent_remind(open_end_at=_NOW, urgent_days=3, already_sent=False, now=_NOW) is False

    def test_門檻為零時只剩訖止前不到一瞬(self) -> None:
        """`ET_URGENT_REMIND_DAYS = 0` 是合法設定（等於停用加急提醒），不該變成「全部都寄」。"""
        assert needs_urgent_remind(open_end_at=_ends_in(hours=1), urgent_days=0, already_sent=False, now=_NOW) is False
