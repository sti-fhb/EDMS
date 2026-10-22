"""週統計之純業務規則（US14 / #325）。

快照的六個數字全部由「每位學員的 `(完成項目數, 總項目數)`」導出，不讀 `ET_ENROLLMENT`
的 `COMPLETION_STATUS`（那欄是死的，只在加入時寫入 `NOT_STARTED`）。故整段可以純函式
驗完，integration 只驗接線與快照真的落地。

## 三個容易寫錯、而且錯了看起來很合理的地方

| 情境 | 正確 | 寫錯的表徵 |
|---|---|---|
| 課程沒有任何項目 | 全部 `NOT_STARTED`、進度 0% | 除零，或每個人都變成「已完課」|
| 沒有任何在籍學員 | 完課率 0%、人數全 0 | 除零 |
| 有人被移除 | 不進母體（呼叫端已濾）| 完課率分母變大、數字永遠偏低 |
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.et.stats.rules import CourseCompletion, progress_delta, rank_lagging_courses, summarize

pytestmark = pytest.mark.unit


class TestSummarize:
    def test_三態人數與完課率(self) -> None:
        stat = summarize(
            {
                "u_done": (4, 4),  # 已完課
                "u_half": (2, 4),  # 進行中
                "u_zero": (0, 4),  # 未開始
                "u_zero2": (0, 4),
            }
        )
        assert stat.cnt_enrolled == 4
        assert (stat.cnt_not_started, stat.cnt_in_progress, stat.cnt_completed) == (2, 1, 1)
        assert stat.completion_rate == Decimal("25.00")

    def test_平均進度為逐學員百分比之平均(self) -> None:
        """與 ET02 頁面顯示的每人進度用**同一支** `completion_pct`——兩邊各算一份的話，
        教師把畫面上的數字自己平均會對不上週報，而兩個都「看起來合理」。"""
        stat = summarize({"a": (1, 4), "b": (3, 4)})  # 25% 與 75%
        assert stat.avg_progress_pct == Decimal("50.00")

    def test_無在籍學員時全為零且不除以零(self) -> None:
        stat = summarize({})
        assert stat.cnt_enrolled == 0
        assert stat.avg_progress_pct == Decimal("0.00")
        assert stat.completion_rate == Decimal("0.00")
        assert (stat.cnt_not_started, stat.cnt_in_progress, stat.cnt_completed) == (0, 0, 0)

    def test_課程無任何項目時全部未開始(self) -> None:
        """教師剛建好課程還沒放內容時很常見。分母為 0 不可推導成「大家都完課了」。"""
        stat = summarize({"a": (0, 0), "b": (0, 0)})
        assert stat.cnt_not_started == 2
        assert stat.cnt_completed == 0
        assert stat.avg_progress_pct == Decimal("0.00")
        assert stat.completion_rate == Decimal("0.00")

    def test_完課率四捨五入至兩位(self) -> None:
        stat = summarize({"a": (1, 1), "b": (0, 1), "c": (0, 1)})  # 1/3
        assert stat.completion_rate == Decimal("33.33")

    def test_全班完課(self) -> None:
        stat = summarize({"a": (2, 2), "b": (2, 2)})
        assert stat.completion_rate == Decimal("100.00")
        assert stat.avg_progress_pct == Decimal("100.00")


class TestProgressDelta:
    def test_有上週快照時回差值(self) -> None:
        assert progress_delta(Decimal("62.00"), Decimal("54.00")) == Decimal("8.00")

    def test_退步為負值(self) -> None:
        """新增章節會讓分母變大，於是平均進度**下降**——這是正常且應如實呈現的。"""
        assert progress_delta(Decimal("40.00"), Decimal("55.00")) == Decimal("-15.00")

    def test_無上週快照回None(self) -> None:
        """AC 5：首次統計時「與上週比較」顯示「—」而非 0 或錯誤。回 `None` 讓呼叫端
        自己決定怎麼顯示；回 `Decimal(0)` 會讓「沒有比較基準」與「持平」變成同一件事。"""
        assert progress_delta(Decimal("62.00"), None) is None


class TestRankLaggingCourses:
    """管理者卡「全體訓練概況」要列出的那幾門（#818）。

    ## 為什麼並列時的排序是獨立的一件事

    **上線當下全站都是 0%**，第一順位完全失效。在那之前排序鍵的第二順位是課程名稱
    （Unicode 碼位序），選出來的幾門與急迫性無關、而且天天相同——管理者會一直盯著
    同一批無意義的課，真正快截止、人最多的那門可能永遠排不進來。

    故並列時改以「截止日近者先 → 在籍人數多者先」決定，最後才以 `course_id` 收尾
    （純為穩定：少了它，同完成率同訖止同人數的兩門課順序由 DB 決定，畫面會自己動）。
    """

    @staticmethod
    def _row(course_id: int, name: str, *, ends_in_days: int | None, enrolled: int, completed: int = 0):
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        return CourseCompletion(
            course_id=course_id,
            course_name=name,
            open_end_at=None if ends_in_days is None else base + timedelta(days=ends_in_days),
            enrolled=enrolled,
            completed=completed,
        )

    def test_完成率由低到高(self) -> None:
        rows = [
            self._row(1, "高", ends_in_days=5, enrolled=10, completed=9),
            self._row(2, "低", ends_in_days=5, enrolled=10, completed=1),
        ]
        assert [r.course_name for r in rank_lagging_courses(rows, limit=5)] == ["低", "高"]

    def test_完成率並列時截止日近者先(self) -> None:
        rows = [
            self._row(1, "晚截止", ends_in_days=30, enrolled=10),
            self._row(2, "快截止", ends_in_days=2, enrolled=10),
        ]
        assert [r.course_name for r in rank_lagging_courses(rows, limit=5)] == ["快截止", "晚截止"]

    def test_截止日也相同時在籍人數多者先(self) -> None:
        """同樣 0%、同一天截止，30 人沒完課比 1 人沒完課急。"""
        rows = [
            self._row(1, "一人", ends_in_days=3, enrolled=1),
            self._row(2, "三十人", ends_in_days=3, enrolled=30),
        ]
        assert [r.course_name for r in rank_lagging_courses(rows, limit=5)] == ["三十人", "一人"]

    def test_無訖止者排在有訖止者之後(self) -> None:
        """沒有截止日就沒有時間壓力，不該插隊到快截止的課前面。"""
        rows = [
            self._row(1, "無訖止", ends_in_days=None, enrolled=50),
            self._row(2, "有訖止", ends_in_days=365, enrolled=1),
        ]
        assert [r.course_name for r in rank_lagging_courses(rows, limit=5)] == ["有訖止", "無訖止"]

    def test_全部並列零完成率時三層鍵一起生效(self) -> None:
        """🔴 這就是上線當天的樣子——第一順位失效，結果完全由後面三層決定。"""
        rows = [
            self._row(1, "ZZ名稱最後但最急", ends_in_days=1, enrolled=5),
            self._row(2, "AA名稱最前但不急", ends_in_days=20, enrolled=99),
            self._row(3, "同日少人", ends_in_days=1, enrolled=2),
        ]
        ranked = [r.course_name for r in rank_lagging_courses(rows, limit=5)]
        assert ranked == ["ZZ名稱最後但最急", "同日少人", "AA名稱最前但不急"]

    def test_超過上限時截斷(self) -> None:
        rows = [self._row(i, f"課{i}", ends_in_days=i, enrolled=1) for i in range(1, 9)]
        ranked = rank_lagging_courses(rows, limit=5)
        assert len(ranked) == 5
        assert [r.course_name for r in ranked] == ["課1", "課2", "課3", "課4", "課5"]

    def test_不足上限時全部回傳(self) -> None:
        rows = [self._row(1, "唯一一門", ends_in_days=3, enrolled=1)]
        assert len(rank_lagging_courses(rows, limit=5)) == 1

    def test_前三鍵全部相同時以課程id收尾(self) -> None:
        """同名同日同人數的兩門課（不同年度的年度訓練）順序必須穩定，否則畫面會自己動。"""
        rows = [
            self._row(9, "ZT年度訓練", ends_in_days=3, enrolled=4),
            self._row(2, "ZT年度訓練", ends_in_days=3, enrolled=4),
        ]
        assert [r.course_id for r in rank_lagging_courses(rows, limit=5)] == [2, 9]
