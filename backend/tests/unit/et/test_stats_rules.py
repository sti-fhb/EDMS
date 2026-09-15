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

from decimal import Decimal

import pytest

from app.et.stats.rules import progress_delta, summarize

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
        """與 ET03 頁面顯示的每人進度用**同一支** `completion_pct`——兩邊各算一份的話，
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
