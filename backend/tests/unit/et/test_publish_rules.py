"""ET 課程發布檢核之純業務規則（#204）。

發布是**單向且有外部後果**的動作——通過即觸發標籤自動邀請並對所有符合標籤的學員
寄信（FR-ET-US3-12，寄信本身屬 `ET-8`）。檢核放過一個空課程，代價是全體學員收到
一封通知去看一門沒有內容的課。故此處逐項與組合都要驗。
"""

from datetime import datetime, timezone

import pytest

from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.publish_rules import (
    BLOCK_NO_CHAPTER,
    BLOCK_NO_MATERIAL,
    BLOCK_NO_SCHEDULE,
    BLOCK_NO_TAG,
    BLOCK_OBSOLETE_DOC,
    BLOCK_QUIZ_NO_QUESTION,
    BLOCK_QUIZ_POINTS,
    CourseSnapshot,
    QuizSummary,
    evaluate_publish,
    is_visible_to_student,
)

pytestmark = pytest.mark.unit


def _dt(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=timezone.utc)


def _snapshot(**overrides) -> CourseSnapshot:
    """一份**恰好可發布**的課程快照；各測試只覆寫想弄壞的那一項。

    這樣寫的用意是：任何一條測試失敗時，失敗原因必然是它覆寫的那一項，
    不會是基準資料本身有第二個問題。
    """
    base = {
        "status": COURSE_DRAFT,
        "open_start_at": _dt(1),
        "open_end_at": _dt(30),
        "tag_count": 1,
        "chapter_count": 1,
        "material_count": 1,
        "quizzes": (),
        "doc_ids": frozenset(),
    }
    return CourseSnapshot(**{**base, **overrides})


class TestEvaluatePublishHappyPath:
    def test_全部滿足時無缺漏(self) -> None:
        assert evaluate_publish(_snapshot(), obsolete_doc_ids=frozenset()) == ()

    def test_未建立問卷不列入缺漏(self) -> None:
        """AC 23：問卷為選配，未建立**不得**因此阻擋發布。

        `CourseSnapshot` 刻意不含問卷欄位——沒有欄位就不可能有人不小心加上這條檢核。
        本測試釘住這個設計，兼作 AC 23 的驗證。
        """
        assert not hasattr(_snapshot(), "survey_count")
        assert evaluate_publish(_snapshot(), obsolete_doc_ids=frozenset()) == ()

    def test_測驗配分剛好一百且有題目時通過(self) -> None:
        snapshot = _snapshot(quizzes=(QuizSummary(quiz_id=1, question_count=2, points_total=100),))
        assert evaluate_publish(snapshot, obsolete_doc_ids=frozenset()) == ()


class TestEvaluatePublishEachCheck:
    def test_無章節被擋(self) -> None:
        blockers = evaluate_publish(_snapshot(chapter_count=0), obsolete_doc_ids=frozenset())
        assert [b.code for b in blockers] == [BLOCK_NO_CHAPTER]

    def test_無教材被擋(self) -> None:
        blockers = evaluate_publish(_snapshot(material_count=0), obsolete_doc_ids=frozenset())
        assert [b.code for b in blockers] == [BLOCK_NO_MATERIAL]

    def test_無標籤被擋(self) -> None:
        blockers = evaluate_publish(_snapshot(tag_count=0), obsolete_doc_ids=frozenset())
        assert [b.code for b in blockers] == [BLOCK_NO_TAG]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"open_start_at": None},
            {"open_end_at": None},
            {"open_start_at": None, "open_end_at": None},
        ],
        ids=["缺起始", "缺訖止", "兩者皆缺"],
    )
    def test_起訖時間未填被擋(self, overrides: dict) -> None:
        """起、訖任一未填皆算缺漏，且**只回一條**——教師要補的是「閱課期間」這件事，
        拆成兩條會讓缺漏清單看起來比實際嚴重。
        """
        blockers = evaluate_publish(_snapshot(**overrides), obsolete_doc_ids=frozenset())
        assert [b.code for b in blockers] == [BLOCK_NO_SCHEDULE]

    @pytest.mark.parametrize("points", [0, 90, 99, 101, 150])
    def test_配分總和非一百被擋(self, points: int) -> None:
        snapshot = _snapshot(quizzes=(QuizSummary(quiz_id=7, question_count=1, points_total=points),))
        blockers = evaluate_publish(snapshot, obsolete_doc_ids=frozenset())
        assert [b.code for b in blockers] == [BLOCK_QUIZ_POINTS]
        assert blockers[0].target_id == 7

    def test_測驗零題被擋(self) -> None:
        """**第六項檢核**——不在 spec AC 24 的五項內。

        來源是 #203 的延後決策：教師逐題新增，空殼測驗與第一題存檔之間必然是 0 題，
        故不能在儲存測驗時擋，只能延到發布。若本 issue 照 AC 字面實作，
        `data-model` §ET_QUESTION 的「同 QUIZ_ID 下至少 1 題」就沒有任何執行點。
        """
        snapshot = _snapshot(quizzes=(QuizSummary(quiz_id=9, question_count=0, points_total=0),))
        codes = [b.code for b in evaluate_publish(snapshot, obsolete_doc_ids=frozenset())]
        assert BLOCK_QUIZ_NO_QUESTION in codes

    def test_零題測驗不另報配分缺漏(self) -> None:
        """0 題的測驗總分必然是 0，同時報「配分不等於 100」只是噪音——
        教師要做的是先加題目，加完配分自然要重算。
        """
        snapshot = _snapshot(quizzes=(QuizSummary(quiz_id=9, question_count=0, points_total=0),))
        assert [b.code for b in evaluate_publish(snapshot, obsolete_doc_ids=frozenset())] == [BLOCK_QUIZ_NO_QUESTION]

    def test_引用廢止文件被擋(self) -> None:
        snapshot = _snapshot(doc_ids=frozenset({"DOC-A", "DOC-B"}))
        blockers = evaluate_publish(snapshot, obsolete_doc_ids=frozenset({"DOC-B"}))
        assert [b.code for b in blockers] == [BLOCK_OBSOLETE_DOC]

    def test_引用未廢止文件通過(self) -> None:
        snapshot = _snapshot(doc_ids=frozenset({"DOC-A"}))
        assert evaluate_publish(snapshot, obsolete_doc_ids=frozenset()) == ()


class TestEvaluatePublishCombined:
    def test_多項缺漏全部列出(self) -> None:
        """AC 26 要求提示**具體缺漏項目**——只回第一項會讓教師修一次、再被擋一次。"""
        snapshot = _snapshot(chapter_count=0, material_count=0, tag_count=0, open_start_at=None)
        codes = {b.code for b in evaluate_publish(snapshot, obsolete_doc_ids=frozenset())}
        assert codes == {BLOCK_NO_CHAPTER, BLOCK_NO_MATERIAL, BLOCK_NO_TAG, BLOCK_NO_SCHEDULE}

    def test_多個測驗各自回報(self) -> None:
        """三個測驗各有各的問題，缺漏清單要能指出是**哪一個**測驗。"""
        snapshot = _snapshot(
            quizzes=(
                QuizSummary(quiz_id=1, question_count=2, points_total=100),  # 正常
                QuizSummary(quiz_id=2, question_count=3, points_total=90),  # 配分不足
                QuizSummary(quiz_id=3, question_count=0, points_total=0),  # 沒題目
            )
        )
        blockers = evaluate_publish(snapshot, obsolete_doc_ids=frozenset())
        assert {(b.code, b.target_id) for b in blockers} == {
            (BLOCK_QUIZ_POINTS, 2),
            (BLOCK_QUIZ_NO_QUESTION, 3),
        }

    def test_訊息不內插使用者輸入(self) -> None:
        """缺漏訊息一律為靜態文案，測驗名稱等使用者輸入以 `target_id` 表達。

        對齊 `sti-error-codes`：訊息內插使用者資料會把它原樣吐回前端，且教師端能看到
        的名稱前端本來就有（課程詳細），不需後端再送一次。
        """
        snapshot = _snapshot(chapter_count=0, quizzes=(QuizSummary(quiz_id=5, question_count=0, points_total=0),))
        for blocker in evaluate_publish(snapshot, obsolete_doc_ids=frozenset()):
            assert "5" not in blocker.message
            assert blocker.message == blocker.message.strip()


class TestIsVisibleToStudent:
    """AC 27 / FR-ET-US3-13：已發布但未到起始時間，學員端不顯示、不可進入。

    學員端清單本身屬 `ET-4`，本 issue 只交付判定函式與其測試——判定寫在這裡，
    `ET-4` 直接呼叫即可，不會出現兩套不一致的可見性規則。
    """

    def test_已發布且已到起始時間可見(self) -> None:
        assert is_visible_to_student(status=COURSE_PUBLISHED, open_start_at=_dt(1), now=_dt(2)) is True

    def test_已發布但未到起始時間不可見(self) -> None:
        assert is_visible_to_student(status=COURSE_PUBLISHED, open_start_at=_dt(10), now=_dt(2)) is False

    def test_剛好等於起始時間可見(self) -> None:
        """`now >= OPEN_START_AT`（data-model §ET_COURSE）——邊界含當下。"""
        assert is_visible_to_student(status=COURSE_PUBLISHED, open_start_at=_dt(5), now=_dt(5)) is True

    @pytest.mark.parametrize("status", [COURSE_DRAFT, COURSE_CLOSED])
    def test_非已發布狀態一律不可見(self, status: str) -> None:
        assert is_visible_to_student(status=status, open_start_at=_dt(1), now=_dt(9)) is False

    def test_起始時間為空不可見(self) -> None:
        """理論上已發布課程必有起始時間（發布檢核擋掉了），但 DB 欄位是 NULLable。
        判定函式不假設上游一定對——空值視為尚未開放，是失敗時較安全的一側。
        """
        assert is_visible_to_student(status=COURSE_PUBLISHED, open_start_at=None, now=_dt(9)) is False
