"""ET05 課後問卷填寫之純業務規則（US13 / #284）。

入口四態導出與作答驗證都不需要 DB，故全部在此以純函式涵蓋；integration 只驗接線、
唯一約束與實際寫了幾列明細。
"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    SURVEY_QUESTION_SINGLE,
    SURVEY_QUESTION_TEXT,
)
from app.et.survey_fill.rules import (
    ANSWER_TEXT_MAX_LEN,
    ENTRY_COURSE_CLOSED,
    ENTRY_FILLABLE,
    ENTRY_HIDDEN,
    ENTRY_SUBMITTED,
    AnswerDraft,
    QuestionSpec,
    build_detail_rows,
    derive_entry_state,
    ensure_fillable,
    validate_answers,
)

pytestmark = pytest.mark.unit

_SINGLE = QuestionSpec(sq_id=1, question_type=SURVEY_QUESTION_SINGLE, option_ids=frozenset({11, 12}))
_SINGLE2 = QuestionSpec(sq_id=2, question_type=SURVEY_QUESTION_SINGLE, option_ids=frozenset({21, 22}))
_TEXT = QuestionSpec(sq_id=3, question_type=SURVEY_QUESTION_TEXT, option_ids=frozenset())


class TestDeriveEntryState:
    """AC 1 / AC 2 / AC 10 / AC 11：側欄入口四態。"""

    def test_完課且問卷啟用且未填為可填(self) -> None:
        assert (
            derive_entry_state(
                survey_active=True, completed=True, already_submitted=False, course_status=COURSE_PUBLISHED
            )
            == ENTRY_FILLABLE
        )

    def test_未完課為隱藏(self) -> None:
        """AC 2：填寫入口在完課前不出現。"""
        assert (
            derive_entry_state(
                survey_active=True, completed=False, already_submitted=False, course_status=COURSE_PUBLISHED
            )
            == ENTRY_HIDDEN
        )

    def test_問卷停用為隱藏(self) -> None:
        assert (
            derive_entry_state(
                survey_active=False, completed=True, already_submitted=False, course_status=COURSE_PUBLISHED
            )
            == ENTRY_HIDDEN
        )

    def test_已填為已送出(self) -> None:
        assert (
            derive_entry_state(
                survey_active=True, completed=True, already_submitted=True, course_status=COURSE_PUBLISHED
            )
            == ENTRY_SUBMITTED
        )

    def test_課程關閉且未填為關閉態(self) -> None:
        """AC 10：入口仍在，點進去只有「課程已關閉」提示。"""
        assert (
            derive_entry_state(survey_active=True, completed=True, already_submitted=False, course_status=COURSE_CLOSED)
            == ENTRY_COURSE_CLOSED
        )

    def test_課程關閉但已填仍可回看(self) -> None:
        """AC 11：關閉不影響已填者的回看——`已填` 必須優先於課程狀態判定。"""
        assert (
            derive_entry_state(survey_active=True, completed=True, already_submitted=True, course_status=COURSE_CLOSED)
            == ENTRY_SUBMITTED
        )

    def test_已填且問卷之後被停用仍可回看(self) -> None:
        """停用只影響「尚未填寫者」（`spec.md` Clarifications）；已填資料保留。

        教師在凍結後仍可停用問卷（`ET_SURVEY_003` 不涵蓋 `IS_ACTIVE`），故這是會真的
        發生的組合，不是理論邊界。
        """
        assert (
            derive_entry_state(
                survey_active=False, completed=True, already_submitted=True, course_status=COURSE_PUBLISHED
            )
            == ENTRY_SUBMITTED
        )

    def test_已填但完課回退仍為已送出(self) -> None:
        """FR-ET-US13-08：完課狀態回退**不使已填問卷失效**。

        教師於學員完課後新增章節就會發生（分母變大 → 百分比下降）。若此處回
        `HIDDEN`，學員的填答會從他眼前消失，而資料其實還在。
        """
        assert (
            derive_entry_state(
                survey_active=True, completed=False, already_submitted=True, course_status=COURSE_PUBLISHED
            )
            == ENTRY_SUBMITTED
        )

    def test_草稿課程為隱藏(self) -> None:
        """草稿課程沒有學員（發布時才產生邀請碼），走到這裡只可能是資料異常。

        回 `HIDDEN` 而非 `COURSE_CLOSED`——後者的訊息是「等再開課」，對一門從未發布
        的課程是錯的指引。
        """
        assert (
            derive_entry_state(survey_active=True, completed=True, already_submitted=False, course_status=COURSE_DRAFT)
            == ENTRY_HIDDEN
        )


class TestEnsureFillable:
    """送出前的狀態守門（AC 8 / AC 10）。"""

    def test_可填狀態通過(self) -> None:
        ensure_fillable(ENTRY_FILLABLE)

    def test_已送出回409(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_fillable(ENTRY_SUBMITTED)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_SURVEY_013"

    def test_課程關閉回409(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_fillable(ENTRY_COURSE_CLOSED)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_SURVEY_014"

    def test_未完課回403(self) -> None:
        """`HIDDEN` 涵蓋未完課 / 問卷停用兩種——對學員而言下一步都是「先把課上完」。

        分兩碼需要 service 多傳一個「為什麼隱藏」，而入口本來就沒顯示，走到這裡的是
        直接打 API 的人。
        """
        with pytest.raises(AppError) as exc:
            ensure_fillable(ENTRY_HIDDEN)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "ET_SURVEY_012"


class TestValidateAnswers:
    """AC 3 / FR-ET-US13-02 / FR-ET-US13-03：單選必答、問答選填。"""

    def test_全部單選已答通過(self) -> None:
        validate_answers(
            questions=[_SINGLE, _SINGLE2],
            answers=[AnswerDraft(sq_id=1, so_id=11), AnswerDraft(sq_id=2, so_id=22)],
        )

    def test_單選未答回422(self) -> None:
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_SINGLE, _SINGLE2], answers=[AnswerDraft(sq_id=1, so_id=11)])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_015"

    def test_未答之題目編號回給前端定位(self) -> None:
        """回「哪幾題」而非只說「有題目未答」——問卷可能有十幾題，逐題紅框才標得出來。"""
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_SINGLE, _SINGLE2, _TEXT], answers=[])
        assert exc.value.extra == {"unanswered_sq_ids": [1, 2]}, "問答題不列入未答"

    def test_問答題留空通過(self) -> None:
        """FR-ET-US13-03：問答題 MUST 為選填，留空 MUST NOT 阻擋送出。

        ⚠️ issue body 驗收條件 3 寫「全部題目作答後方可送出」，那是 #238 加入問答題
        （2026-08-28）之前的敘述，以 spec 為準。
        """
        validate_answers(questions=[_SINGLE, _TEXT], answers=[AnswerDraft(sq_id=1, so_id=11)])

    def test_問答題只打空白視為留空(self) -> None:
        validate_answers(
            questions=[_SINGLE, _TEXT],
            answers=[AnswerDraft(sq_id=1, so_id=11), AnswerDraft(sq_id=3, answer_text="   ")],
        )

    def test_問答題超過上限回422(self) -> None:
        with pytest.raises(AppError) as exc:
            validate_answers(
                questions=[_TEXT], answers=[AnswerDraft(sq_id=3, answer_text="字" * (ANSWER_TEXT_MAX_LEN + 1))]
            )
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_016"

    def test_問答題恰好上限通過(self) -> None:
        validate_answers(questions=[_TEXT], answers=[AnswerDraft(sq_id=3, answer_text="字" * ANSWER_TEXT_MAX_LEN)])

    def test_單選題送出不屬該題之選項回422(self) -> None:
        """否則學員可送出別題的選項 id，讓 US9 的統計出現不屬於該題的選項。"""
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_SINGLE, _SINGLE2], answers=[AnswerDraft(sq_id=1, so_id=21)])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_017"

    def test_單選題送出文字回422(self) -> None:
        """`SO_ID` 與 `ANSWER_TEXT` 互斥，由應用層把關（`data-model` 明示不設 CHECK）。"""
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_SINGLE], answers=[AnswerDraft(sq_id=1, so_id=11, answer_text="順便寫幾句")])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_017"

    def test_問答題送出選項回422(self) -> None:
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_TEXT], answers=[AnswerDraft(sq_id=3, so_id=11)])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_017"

    def test_送出不存在之題目回422(self) -> None:
        """題目在填答期間被刪除（或前端送錯）——不可靜默忽略。

        忽略的話學員以為那一題送出去了，而 `_D` 裡沒有那一列，US9 的已答人數少一。
        """
        with pytest.raises(AppError) as exc:
            validate_answers(questions=[_SINGLE], answers=[AnswerDraft(sq_id=99, so_id=11)])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_017"

    def test_同一題送兩次回422(self) -> None:
        """`(RESPONSE_ID, SQ_ID)` 唯一——放它掉進 INSERT 會撞約束變成 500。"""
        with pytest.raises(AppError) as exc:
            validate_answers(
                questions=[_SINGLE], answers=[AnswerDraft(sq_id=1, so_id=11), AnswerDraft(sq_id=1, so_id=12)]
            )
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_SURVEY_017"


class TestBuildDetailRows:
    """SA Q1 裁示 A：留空的問答題**不寫入** `ET_SURVEY_RESPONSE_D`。"""

    def test_留空之問答題不進明細(self) -> None:
        rows = build_detail_rows(
            questions=[_SINGLE, _TEXT],
            answers=[AnswerDraft(sq_id=1, so_id=11), AnswerDraft(sq_id=3, answer_text="")],
        )
        assert [r.sq_id for r in rows] == [1], "表裡有列 ⇔ 學員答了這題"

    def test_完全沒送問答題也不進明細(self) -> None:
        rows = build_detail_rows(questions=[_SINGLE, _TEXT], answers=[AnswerDraft(sq_id=1, so_id=11)])
        assert [r.sq_id for r in rows] == [1]

    def test_只打空白之問答題不進明細(self) -> None:
        """避免寫進一列內容為空白的「已答」——US9 會把它算成有回饋的人。"""
        rows = build_detail_rows(questions=[_TEXT], answers=[AnswerDraft(sq_id=3, answer_text=" \t ")])
        assert rows == []

    def test_有填之問答題寫入去除前後空白的文字(self) -> None:
        rows = build_detail_rows(questions=[_TEXT], answers=[AnswerDraft(sq_id=3, answer_text="  影片可以再短一些  ")])
        assert len(rows) == 1
        assert rows[0].sq_id == 3
        assert rows[0].so_id is None
        assert rows[0].answer_text == "影片可以再短一些"

    def test_單選題之明細文字欄為空(self) -> None:
        rows = build_detail_rows(questions=[_SINGLE], answers=[AnswerDraft(sq_id=1, so_id=12)])
        assert len(rows) == 1
        assert rows[0].so_id == 12
        assert rows[0].answer_text is None

    def test_明細順序依題目順序而非送出順序(self) -> None:
        """前端可能以任意順序送出（例如先填了第 3 題）。

        明細列的順序決定 US9 明細檢視的呈現順序；依題目順序寫入，那一頁就不必再排序。
        """
        rows = build_detail_rows(
            questions=[_SINGLE, _SINGLE2, _TEXT],
            answers=[
                AnswerDraft(sq_id=3, answer_text="意見"),
                AnswerDraft(sq_id=2, so_id=21),
                AnswerDraft(sq_id=1, so_id=11),
            ],
        )
        assert [r.sq_id for r in rows] == [1, 2, 3]
