"""ET 課後問卷之純業務規則（#204）。"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED, SURVEY_QUESTION_SINGLE, SURVEY_QUESTION_TEXT
from app.et.survey.rules import (
    MIN_OPTIONS,
    ensure_editable,
    ensure_option_count_valid,
    ensure_options_match_type,
    ensure_question_reorder_complete,
    ensure_survey_absent,
    ensure_survey_deletable,
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


class TestEnsureOptionsMatchType:
    """題型與選項數之搭配（#238）。

    取代了原本無條件套用的 `ensure_option_count_valid`——問答題沒有選項可言。
    """

    @pytest.mark.parametrize("count", [2, 3, 10])
    def test_單選題達下限通過(self, count: int) -> None:
        ensure_options_match_type(SURVEY_QUESTION_SINGLE, option_count=count)

    @pytest.mark.parametrize("count", [0, 1])
    def test_單選題不足兩個被擋(self, count: int) -> None:
        with pytest.raises(AppError) as exc:
            ensure_options_match_type(SURVEY_QUESTION_SINGLE, option_count=count)
        assert exc.value.error_code == "ET_SURVEY_004"

    def test_問答題零個選項通過(self) -> None:
        ensure_options_match_type(SURVEY_QUESTION_TEXT, option_count=0)

    @pytest.mark.parametrize("count", [1, 2, 5])
    def test_問答題帶選項被擋(self, count: int) -> None:
        """**明確擋下而非靜默忽略**。

        教師把單選題改成問答題時，原本填的選項若被無聲丟棄，他會以為還在。
        擋下來並提示，前端才有機會告訴他「切換題型會清空選項」。
        """
        with pytest.raises(AppError) as exc:
            ensure_options_match_type(SURVEY_QUESTION_TEXT, option_count=count)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_008"

    def test_兩種題型的錯誤碼不同(self) -> None:
        """單選題選項不足是 `ET_SURVEY_004`、問答題誤帶選項是 `ET_SURVEY_008`——
        前端要靠 error_code 分辨該提示「請再加一個選項」還是「問答題不能有選項」。
        """
        with pytest.raises(AppError) as single_exc:
            ensure_options_match_type(SURVEY_QUESTION_SINGLE, option_count=1)
        with pytest.raises(AppError) as text_exc:
            ensure_options_match_type(SURVEY_QUESTION_TEXT, option_count=1)
        assert single_exc.value.error_code != text_exc.value.error_code


class TestEnsureSurveyDeletable:
    """僅草稿課程之問卷可刪除（#238）。"""

    def test_草稿課程可刪(self) -> None:
        ensure_survey_deletable(COURSE_DRAFT)

    @pytest.mark.parametrize("status", [COURSE_PUBLISHED, COURSE_CLOSED])
    def test_非草稿被擋(self, status: str) -> None:
        """已發布 / 已關閉一律只能停用。

        「已關閉」也擋是因為關閉可逆（再開課後學員又看得到），若允許在關閉期間刪問卷，
        再開課後學員的填答入口就無故消失了。
        """
        with pytest.raises(AppError) as exc:
            ensure_survey_deletable(status)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_007"

    def test_訊息指向替代動作(self) -> None:
        """比照 `ET_COURSE_005`（「僅草稿課程可刪除，已發布課程請改用關閉」）——
        只說不能刪、不說能做什麼，教師會卡住。
        """
        with pytest.raises(AppError) as exc:
            ensure_survey_deletable(COURSE_PUBLISHED)
        assert "停用" in exc.value.detail


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
