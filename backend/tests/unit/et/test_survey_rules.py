"""ET 課後問卷之純業務規則（#204）。"""

import pytest

from app.core.exceptions import AppError
from app.et.survey.rules import (
    MIN_OPTIONS,
    ensure_editable,
    ensure_option_count_valid,
    ensure_question_reorder_complete,
    ensure_survey_absent,
    resequence_questions,
)

pytestmark = pytest.mark.unit


class TestEnsureSurveyAbsent:
    def test_尚無問卷通過(self) -> None:
        ensure_survey_absent(exists=False)

    def test_已有問卷被擋(self) -> None:
        """AC 22 / ET-MSG-ET02-010：一門課程 0～1 份。"""
        with pytest.raises(AppError) as exc:
            ensure_survey_absent(exists=True)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_SURVEY_002"


class TestEnsureOptionCountValid:
    @pytest.mark.parametrize("count", [2, 3, 5, 10])
    def test_達下限通過(self, count: int) -> None:
        ensure_option_count_valid(count)

    @pytest.mark.parametrize("count", [0, 1])
    def test_不足兩個被擋(self, count: int) -> None:
        """AC 19 / ET-MSG-ET02-008：每題至少需 2 個選項。

        只有一個選項的題目沒有選擇可言；0 個則連題目都不成立。
        """
        with pytest.raises(AppError) as exc:
            ensure_option_count_valid(count)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_004"

    def test_無上限(self) -> None:
        """`data-model` §ET_SURVEY_OPTION 只訂下限 2、**未訂上限**——與測驗題目
        （2–6，`ET_QUESTION_003`）不同，不可照抄。上限交由 schema 之 `max_length`
        作為請求大小防護，不是業務規則。
        """
        assert MIN_OPTIONS == 2
        ensure_option_count_valid(50)


class TestEnsureEditable:
    def test_無填答時可編修(self) -> None:
        """AC 20：尚無任何填答時允許自由編修題目與選項。"""
        ensure_editable(has_responses=False)

    def test_有填答即凍結(self) -> None:
        """AC 21 / ET-MSG-ET02-009：已有任何填答即凍結題目與選項。

        凍結的判定是「**是否存在**任何未刪除之填答」，不是「幾筆」——一個人填了，
        題目就不能再改，否則他填的答案會對應到不存在的題目。
        """
        with pytest.raises(AppError) as exc:
            ensure_editable(has_responses=True)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_003"


class TestEnsureQuestionReorderComplete:
    def test_完整涵蓋通過(self) -> None:
        ensure_question_reorder_complete(current_ids={1, 2, 3}, requested=[3, 1, 2])

    def test_空問卷送空陣列通過(self) -> None:
        ensure_question_reorder_complete(current_ids=set(), requested=[])

    @pytest.mark.parametrize(
        "requested",
        [[1, 1, 2], [1, 2], [1, 2, 3, 4], [1, 2, 9]],
        ids=["有重複", "有缺漏", "多出不存在的", "夾帶他人題目"],
    )
    def test_不一致被擋(self, requested: list[int]) -> None:
        """長度與集合都要檢查：`[1, 1, 2]` 的集合等同 `{1, 2}`，只比集合會漏掉重複；
        集合比對則擋下缺漏與夾帶他人問卷題目 ID 的越權嘗試。
        """
        with pytest.raises(AppError) as exc:
            ensure_question_reorder_complete(current_ids={1, 2, 3}, requested=requested)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_006"

    def test_錯誤碼與測驗題目重排不同(self) -> None:
        """問卷題目重排回 `ET_SURVEY_006`、測驗題目重排回 `ET_QUESTION_004`——
        共用單一代碼會使前端無從分辨是哪一層的重排失敗。
        """
        with pytest.raises(AppError) as exc:
            ensure_question_reorder_complete(current_ids={1}, requested=[])
        assert exc.value.error_code != "ET_QUESTION_004"


class TestResequenceQuestions:
    def test_自一起連續編號(self) -> None:
        assert resequence_questions([7, 3, 5]) == {7: 1, 3: 2, 5: 3}

    def test_空陣列回空(self) -> None:
        assert resequence_questions([]) == {}
