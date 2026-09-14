"""ET06 測驗作答之純業務規則（US6 / #279）。

本檔是這張 issue 的重心——計分、剩餘次數、逾時判定全部是純函式，**完全不需要 DB
就能驗完**。integration 只驗接線與快照真的寫進去了。

## 計分的三個邊界是同一條公式的三面

多選題 `max(0, (對 − 誤) ÷ 應選 × 配分)`：

| 邊界 | 值 | 為何 |
|---|---|---|
| 誤選 > 答對 | **0，不是負分** | 負分會讓這題倒扣其他題的分數 |
| 分母 | **應選正確數** | 不是選項總數、也不是學員選的數量 |
| 完全未勾選 | **0** | 不是「沒有誤選所以拿部分分」 |
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.et.attempt.rules import (
    AnswerSnapshot,
    OptionSnapshot,
    can_start_attempt,
    grade_details,
    is_timed_out,
    remaining_attempts,
    remaining_seconds,
    round_used_attempts,
    score_question,
    shuffled,
)
from app.et.constants import QUESTION_MULTIPLE, QUESTION_SINGLE

pytestmark = pytest.mark.unit


def _options(*flags: bool) -> list[OptionSnapshot]:
    """依 `is_correct` 旗標產生選項；`option_id` 由 1 起編。"""
    return [OptionSnapshot(option_id=i, text=f"選項{i}", is_correct=flag) for i, flag in enumerate(flags, start=1)]


class TestScoreSingle:
    """單選題：全有全無（FR-ET-US6-07）。"""

    def test_答對得配分(self) -> None:
        options = _options(False, True, False)
        assert score_question(QUESTION_SINGLE, [2], options, points=20) == Decimal("20")

    def test_答錯得零(self) -> None:
        options = _options(False, True, False)
        assert score_question(QUESTION_SINGLE, [1], options, points=20) == Decimal("0")

    def test_未作答得零(self) -> None:
        assert score_question(QUESTION_SINGLE, [], _options(False, True), points=20) == Decimal("0")

    def test_選了多個視為答錯(self) -> None:
        """單選題不該收到多個選項（radio 只能選一個）。

        真的收到就是前端壞了或有人繞過 UI——此時**不可**因為「其中一個是對的」就給分。
        """
        options = _options(False, True, False)
        assert score_question(QUESTION_SINGLE, [1, 2], options, points=20) == Decimal("0")


class TestScoreMultiple:
    """多選題：部分計分（FR-ET-US6-07）。"""

    def test_wireframe_之範例(self) -> None:
        """wireframe 結果頁 Q2：應選 4（A/B/C/E）、配分 20、答對 3、誤選 0 → 15 分。

        直接取自 `docs/wireframes/et/index.html` 的 `quiz-result`，該處顯示「15 / 20」。
        """
        options = _options(True, True, True, False, True)  # A B C E 正確、D 錯
        assert score_question(QUESTION_MULTIPLE, [1, 2, 3], options, points=20) == Decimal("15")

    def test_spec_之範例(self) -> None:
        """`spec_us6` 場景 14：應選 3、配分 30、答對 2、誤選 1 → `max(0,(2−1)÷3×30)` = 10。"""
        options = _options(True, True, True, False)
        assert score_question(QUESTION_MULTIPLE, [1, 2, 4], options, points=30) == Decimal("10")

    def test_全對得滿分(self) -> None:
        options = _options(True, True, False)
        assert score_question(QUESTION_MULTIPLE, [1, 2], options, points=30) == Decimal("30")

    def test_誤選多於答對得零而非負分(self) -> None:
        """**公式的 `max` 不是防呆，是規則**——負分會讓這題倒扣其他題的分數。"""
        options = _options(True, True, True, False, False)
        assert score_question(QUESTION_MULTIPLE, [1, 4, 5], options, points=30) == Decimal("0")

    def test_完全未作答得零(self) -> None:
        """不是「沒有誤選所以拿部分分」。"""
        options = _options(True, True, False)
        assert score_question(QUESTION_MULTIPLE, [], options, points=30) == Decimal("0")

    def test_分母是應選正確數而非選項總數(self) -> None:
        """5 個選項、其中 2 個正確；答對 1 個 → `1÷2×20 = 10`，不是 `1÷5×20 = 4`。"""
        options = _options(True, True, False, False, False)
        assert score_question(QUESTION_MULTIPLE, [1], options, points=20) == Decimal("10")

    def test_四捨五入至兩位(self) -> None:
        """`SCORE` 為 `DECIMAL(5,2)`；`1÷3×20 = 6.666…` → 6.67。"""
        options = _options(True, True, True)
        assert score_question(QUESTION_MULTIPLE, [1], options, points=20) == Decimal("6.67")

    def test_無正確選項時回零而非除零(self) -> None:
        """建題時強制至少 1 個正確選項（`data-model`），但資料異常不該讓學員的提交 500。"""
        assert score_question(QUESTION_MULTIPLE, [1], _options(False, False), points=20) == Decimal("0")


class TestAttemptCounting:
    """重考次數（`data-model` §ET_QUIZ_RETRY_RESET 之公式）。"""

    def test_未曾重置時本輪已用等於總次數(self) -> None:
        assert round_used_attempts(total=2, reset_base=0) == 2

    def test_重置後以基準扣抵(self) -> None:
        """重置紀錄存的是「重置當下的既有 attempt 總數」，作為本輪的起算基準。"""
        assert round_used_attempts(total=5, reset_base=4) == 1

    def test_max_retry_為零時仍可作答一次(self) -> None:
        """**最容易寫反的一條**：`MAX_RETRY = 0` 是「只能作答 1 次」，不是「不能作答」。

        總可作答次數 = `MAX_RETRY + 1`（見 `quiz/models.py`）。
        """
        assert can_start_attempt(total=0, reset_base=0, max_retry=0) is True
        assert can_start_attempt(total=1, reset_base=0, max_retry=0) is False

    def test_max_retry_為三時可作答四次(self) -> None:
        for used in range(4):
            assert can_start_attempt(total=used, reset_base=0, max_retry=3) is True
        assert can_start_attempt(total=4, reset_base=0, max_retry=3) is False

    def test_重置後恢復可作答(self) -> None:
        """次數用盡（4 次）後教師重置 → 基準設為 4，本輪從 0 起算。"""
        assert can_start_attempt(total=4, reset_base=0, max_retry=3) is False
        assert can_start_attempt(total=4, reset_base=4, max_retry=3) is True

    def test_剩餘次數(self) -> None:
        assert remaining_attempts(total=0, reset_base=0, max_retry=3) == 4
        assert remaining_attempts(total=3, reset_base=0, max_retry=3) == 1
        assert remaining_attempts(total=4, reset_base=0, max_retry=3) == 0

    def test_剩餘次數不為負(self) -> None:
        """資料異常（attempt 比允許的多）時回 0，不是負數。"""
        assert remaining_attempts(total=9, reset_base=0, max_retry=3) == 0


class TestTiming:
    """伺服器權威計時——前端的倒數只是顯示。"""

    _started = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)

    def test_不限時永不逾時(self) -> None:
        """`TIME_LIMIT_SNAPSHOT` 為 `None` 是「不限時」，**不是 0 分鐘**。"""
        far_future = self._started + timedelta(days=30)
        assert is_timed_out(started_at=self._started, time_limit_min=None, now=far_future) is False

    def test_不限時之剩餘秒數為_None(self) -> None:
        assert remaining_seconds(started_at=self._started, time_limit_min=None, now=self._started) is None

    def test_時限內未逾時(self) -> None:
        now = self._started + timedelta(minutes=9, seconds=59)
        assert is_timed_out(started_at=self._started, time_limit_min=10, now=now) is False
        assert remaining_seconds(started_at=self._started, time_limit_min=10, now=now) == 1

    def test_超過時限即逾時(self) -> None:
        now = self._started + timedelta(minutes=10, seconds=1)
        assert is_timed_out(started_at=self._started, time_limit_min=10, now=now) is True

    def test_逾時後剩餘秒數為零而非負(self) -> None:
        now = self._started + timedelta(minutes=30)
        assert remaining_seconds(started_at=self._started, time_limit_min=10, now=now) == 0

    def test_剩餘秒數自_started_at_起算而非自本次載入(self) -> None:
        """wireframe 引導頁明訂「中途離開或關閉視窗**仍持續扣時間**」。

        學員關掉分頁 5 分鐘後回來，10 分鐘的測驗只剩 5 分鐘——若改成「每次載入重新
        起算」，關掉再開就能無限延長。
        """
        now = self._started + timedelta(minutes=5)
        assert remaining_seconds(started_at=self._started, time_limit_min=10, now=now) == 300


class TestShuffled:
    def test_是原集合的重排(self) -> None:
        ids = [11, 22, 33, 44, 55]
        assert sorted(shuffled(ids)) == sorted(ids)

    def test_不修改輸入(self) -> None:
        ids = [1, 2, 3]
        shuffled(ids)
        assert ids == [1, 2, 3]

    def test_空清單回空(self) -> None:
        assert shuffled([]) == []


class TestGradeDetails:
    """整份考卷的閱卷（#325 由 `submit()` 抽出）。

    抽出的理由不是整潔，是**它即將有第二個呼叫端**：SCHET002 結清逾期未提交的 attempt
    時（#317）要用同一套判定。及格與否的那道正規化若複製一份，兩邊遲早分岔，而分岔的
    表徵是「同一份考卷，學員自己按提交及格、被排程結清就不及格」——沒有任何錯誤訊息。
    """

    @staticmethod
    def _answer(question_id: int, *, points: int, correct: bool) -> AnswerSnapshot:
        """單選題一題：`correct=True` 表示學員選中正確選項。"""
        return AnswerSnapshot(
            question_id=question_id,
            question_type=QUESTION_SINGLE,
            selected=[2] if correct else [1],
            options=_options(False, True),
            points=points,
        )

    def test_逐題得分與總分(self) -> None:
        answers = [
            self._answer(101, points=60, correct=True),
            self._answer(102, points=40, correct=False),
        ]
        result = grade_details(answers, pass_score=Decimal("80"))
        assert result.per_question == {101: Decimal("60.00"), 102: Decimal("0.00")}
        assert result.total == Decimal("60.00")
        assert result.points_total == 100

    def test_配分總和100時達及格分數即及格(self) -> None:
        answers = [self._answer(101, points=80, correct=True), self._answer(102, points=20, correct=False)]
        assert grade_details(answers, pass_score=Decimal("80")).is_pass is True

    def test_配分總和被改大時不因絕對分數達標而及格(self) -> None:
        """教師於發布後把配分總和改成 300：答對 100 分（三分之一）**不**該及格。

        「各題配分總和 = 100」只在發布當下檢核，發布後仍可改配分或增刪題目。
        直接拿總分比及格分數，這裡會誤判為及格。
        """
        answers = [
            self._answer(101, points=100, correct=True),
            self._answer(102, points=100, correct=False),
            self._answer(103, points=100, correct=False),
        ]
        result = grade_details(answers, pass_score=Decimal("80"))
        assert result.total == Decimal("100.00")
        assert result.points_total == 300
        assert result.is_pass is False

    def test_配分總和被改小時全對仍應及格(self) -> None:
        """配分總和被改成 50：直接比較的話**任何人都不可能**及格，整門課後半段永久鎖死。"""
        answers = [self._answer(101, points=25, correct=True), self._answer(102, points=25, correct=True)]
        result = grade_details(answers, pass_score=Decimal("80"))
        assert result.total == Decimal("50.00")
        assert result.is_pass is True

    def test_零題不及格且不除以零(self) -> None:
        result = grade_details([], pass_score=Decimal("80"))
        assert result.points_total == 0
        assert result.total == Decimal(0)
        assert result.is_pass is False

    def test_配分全為零不及格且不除以零(self) -> None:
        answers = [self._answer(101, points=0, correct=True)]
        assert grade_details(answers, pass_score=Decimal("80")).is_pass is False
