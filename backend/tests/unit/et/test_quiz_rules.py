"""ET 測驗題目純業務規則（#203）。"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import QUESTION_MULTIPLE, QUESTION_SINGLE
from app.et.quiz.rules import ensure_correct_options_valid, ensure_option_count_valid, resequence_questions

pytestmark = pytest.mark.unit


class TestEnsureOptionCountValid:
    @pytest.mark.parametrize("count", [2, 3, 4, 5, 6])
    def test_範圍內通過(self, count: int) -> None:
        ensure_option_count_valid(count)

    @pytest.mark.parametrize("count", [0, 1, 7, 100])
    def test_超出範圍被擋(self, count: int) -> None:
        with pytest.raises(AppError) as exc:
            ensure_option_count_valid(count)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_QUESTION_003"

    def test_只剩一個選項被擋(self) -> None:
        """刪選項刪到剩 1 個時的情境——只有一個選項的題目沒有選擇可言。"""
        with pytest.raises(AppError) as exc:
            ensure_option_count_valid(1)
        assert exc.value.error_code == "ET_QUESTION_003"


class TestEnsureCorrectOptionsValid:
    def test_單選題恰好一個正確通過(self) -> None:
        ensure_correct_options_valid(QUESTION_SINGLE, correct_count=1)

    @pytest.mark.parametrize("count", [0, 2, 3])
    def test_單選題非恰好一個被擋(self, count: int) -> None:
        """0 個 → 評分爆掉；2 個以上 →「正確答案」失去意義。

        spec 只明訂多選題的規則，單選題這條是 SD 補上的——前端 radio 天然只能選一個，
        這裡擋的是繞過 UI 直接打 API 的請求。
        """
        with pytest.raises(AppError) as exc:
            ensure_correct_options_valid(QUESTION_SINGLE, correct_count=count)
        assert exc.value.error_code == "ET_QUESTION_002"

    @pytest.mark.parametrize("count", [1, 2, 3, 6])
    def test_多選題至少一個通過(self, count: int) -> None:
        ensure_correct_options_valid(QUESTION_MULTIPLE, correct_count=count)

    def test_多選題零個正確被擋(self) -> None:
        """data-model 明訂：避免部分計分公式分母為 0（ET-MSG-ET02-004）。"""
        with pytest.raises(AppError) as exc:
            ensure_correct_options_valid(QUESTION_MULTIPLE, correct_count=0)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_QUESTION_002"

    def test_兩種題型之訊息可區辨(self) -> None:
        """單選與多選的違規原因不同，訊息不該一樣——否則教師不知道要怎麼改。"""
        with pytest.raises(AppError) as single_exc:
            ensure_correct_options_valid(QUESTION_SINGLE, correct_count=2)
        with pytest.raises(AppError) as multi_exc:
            ensure_correct_options_valid(QUESTION_MULTIPLE, correct_count=0)
        assert single_exc.value.detail != multi_exc.value.detail


class TestResequenceQuestions:
    def test_依陣列順序自_1_起編號(self) -> None:
        assert resequence_questions([30, 10, 20]) == {30: 1, 10: 2, 20: 3}

    def test_單題(self) -> None:
        assert resequence_questions([7]) == {7: 1}

    def test_空清單(self) -> None:
        assert resequence_questions([]) == {}
