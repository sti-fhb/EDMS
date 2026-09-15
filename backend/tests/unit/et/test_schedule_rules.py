"""ET 排程之純業務規則（US14 / #325、#317）。

結清時機的判定有兩條獨立路徑，兩條都漏掉任一邊會造成相反方向的錯誤：

| 漏掉 | 後果 |
|---|---|
| 時限已過這條 | 限時測驗要多等 24 小時才結清（無害，只是慢）|
| 寬限期這條 | **不限時測驗永遠不會被結清**——那正是 #317 最寬的一側，等於整個修復失效 |
| 兩條都不檢查（課程一關就結清）| 學員手上還有合法作答時間的考卷被收走，推翻 `spec_us6` 場景 27 |
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.et.schedules.rules import SETTLE_GRACE_HOURS, should_settle

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


class TestShouldSettle:
    def test_時限已過即可結清(self) -> None:
        """限時測驗的時限一到就沒有合法作答時間了，不必再等寬限期。"""
        just_closed = _NOW - timedelta(minutes=1)
        assert should_settle(closed_since=just_closed, timed_out=True, now=_NOW) is True

    def test_時限未到且寬限期內不結清(self) -> None:
        """學員 07:30 開始 60 分鐘測驗、課程 08:00 到期、排程 08:00 執行——
        他還有 30 分鐘合法時間，不可被強制交卷（`spec_us6` 場景 27）。"""
        just_closed = _NOW - timedelta(minutes=1)
        assert should_settle(closed_since=just_closed, timed_out=False, now=_NOW) is False

    def test_不限時測驗滿寬限期後結清(self) -> None:
        """本缺口最寬的一側：`is_timed_out` 對不限時測驗恆為 `False`，
        只能靠寬限期收斂，否則等於沒修。"""
        long_closed = _NOW - timedelta(hours=SETTLE_GRACE_HOURS)
        assert should_settle(closed_since=long_closed, timed_out=False, now=_NOW) is True

    def test_剛好差一秒未滿寬限期不結清(self) -> None:
        almost = _NOW - timedelta(hours=SETTLE_GRACE_HOURS) + timedelta(seconds=1)
        assert should_settle(closed_since=almost, timed_out=False, now=_NOW) is False

    def test_關閉時點缺漏仍可結清(self) -> None:
        """已關閉卻沒有任何時點屬資料異常——不該因為缺一個時間戳就讓 attempt 永遠留著。"""
        assert should_settle(closed_since=None, timed_out=False, now=_NOW) is True

    def test_積壓的舊課程立即結清(self) -> None:
        """本作業上線前就關閉的課程，其殘留 attempt 早已超過寬限期，首輪即清掉。"""
        ancient = _NOW - timedelta(days=90)
        assert should_settle(closed_since=ancient, timed_out=False, now=_NOW) is True
