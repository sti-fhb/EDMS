"""ET04 加入課程與我的課程清單之純業務規則（US4 / #247）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AppError
from app.et.constants import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    COMPLETION_NOT_STARTED,
    COURSE_CLOSED,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
)
from app.et.enrollment.rules import (
    INVITATION_CODE_LENGTH,
    derive_completion_status,
    ensure_course_joinable,
    ensure_not_removed,
    is_course_completed,
    is_listed_in_my_courses,
    normalize_invitation_code,
)
from app.et.progress.repository import completion_pct

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


class TestNormalizeInvitationCode:
    """AC 5：僅接受 8 碼純數字。"""

    @pytest.mark.parametrize("raw", ["12345678", "00000000", "99999999"])
    def test_八碼純數字通過(self, raw: str) -> None:
        assert normalize_invitation_code(raw) == raw

    def test_長度常數與欄位一致(self) -> None:
        """`ET_COURSE.INVITATION_CODE` 為 VARCHAR(8)。"""
        assert INVITATION_CODE_LENGTH == 8

    def test_前後空白會被去除(self) -> None:
        """使用者從通訊軟體複製邀請碼時常帶空白，那不是輸入錯誤。"""
        assert normalize_invitation_code("  12345678 ") == "12345678"

    @pytest.mark.parametrize(
        "raw",
        [
            "1234567",  # 7 碼
            "123456789",  # 9 碼
            "1234567a",  # 含字母
            "1234-678",  # 含符號
            "",
            "   ",
            "12345678\n12345678",  # 換行拼接
        ],
    )
    def test_格式不符回_None(self, raw: str) -> None:
        assert normalize_invitation_code(raw) is None

    def test_全形數字不算數字(self) -> None:
        """`str.isdigit()` 對全形數字回 True，`int()` 也吃——故必須用 ASCII 明確比對。

        全形碼查 DB 必然查無，回 None 讓它走「格式不符」而非查詢一次再回 404。
        """
        assert normalize_invitation_code("１２３４５６７８") is None


class TestEnsureCourseJoinable:
    def test_已發布課程可加入(self) -> None:
        ensure_course_joinable(course_status=COURSE_PUBLISHED, open_end_at=_NOW + timedelta(days=1), now=_NOW)

    def test_已關閉課程被擋(self) -> None:
        """AC 9 / ET-MSG-ET04-002：邀請碼於關閉期間失效、再開課後恢復有效。

        故判定依據是**課程當前狀態**，不是碼本身存不存在。
        """
        with pytest.raises(AppError) as exc:
            ensure_course_joinable(course_status=COURSE_CLOSED, open_end_at=_NOW + timedelta(days=1), now=_NOW)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_ENROLL_002"

    def test_草稿課程視為查無(self) -> None:
        """邀請碼於發布時才產生，草稿課程照理取不到碼。

        真的走到這裡只可能是資料異常；回 404（而非「關閉中」）以免向未受邀者
        洩漏一門尚未發布之課程的存在。
        """
        with pytest.raises(AppError) as exc:
            ensure_course_joinable(course_status=COURSE_DRAFT, open_end_at=_NOW + timedelta(days=1), now=_NOW)
        assert exc.value.status_code == 404
        assert exc.value.error_code == "ET_ENROLL_001"


class TestEnsureNotRemoved:
    def test_未被移除通過(self) -> None:
        ensure_not_removed(is_removed=False)

    def test_已被移除者不可自行重新加入(self) -> None:
        """#247 SA Q1 裁示 C。

        必須在應用層明確擋下並給訊息——否則會掉進 INSERT 撞
        `UQ_ET_ENROLLMENT_USER_COURSE`，變成 500，且衝突對象是一筆學員看不見的列。
        """
        with pytest.raises(AppError) as exc:
            ensure_not_removed(is_removed=True)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_ENROLL_003"


class TestIsListedInMyCourses:
    """AC 4 / AC 5：清單可見性。"""

    def test_已發布且已開始可見(self) -> None:
        assert is_listed_in_my_courses(
            status=COURSE_PUBLISHED,
            open_start_at=_NOW - timedelta(days=1),
            open_end_at=_NOW + timedelta(days=1),
            now=_NOW,
        )

    def test_起始時間未到不可見(self) -> None:
        """AC 4：起始時間未到之課程不顯示於清單。"""
        assert not is_listed_in_my_courses(
            status=COURSE_PUBLISHED,
            open_start_at=_NOW + timedelta(minutes=1),
            open_end_at=_NOW + timedelta(days=1),
            now=_NOW,
        )

    def test_恰好等於起始時間即可見(self) -> None:
        """邊界沿用 `publish_rules.is_visible_to_student` 之 `now >= open_start_at`。"""
        assert is_listed_in_my_courses(
            status=COURSE_PUBLISHED, open_start_at=_NOW, open_end_at=_NOW + timedelta(days=1), now=_NOW
        )

    def test_起始時間為空不可見(self) -> None:
        assert not is_listed_in_my_courses(
            status=COURSE_PUBLISHED, open_start_at=None, open_end_at=_NOW + timedelta(days=1), now=_NOW
        )

    def test_草稿不可見(self) -> None:
        assert not is_listed_in_my_courses(
            status=COURSE_DRAFT, open_start_at=_NOW - timedelta(days=1), open_end_at=_NOW + timedelta(days=1), now=_NOW
        )

    @pytest.mark.parametrize("open_start_at", [_NOW - timedelta(days=1), _NOW + timedelta(days=1), None])
    def test_已關閉課程一律可見(self, open_start_at: datetime | None) -> None:
        """AC 5 / AC 13：已關閉課程顯示「已關閉」標示、可唯讀回看。

        這是 `ET-4` 與 `publish_rules.is_visible_to_student` 的分歧點——後者對
        `CLOSED` 回 False（它問的是「能否**開始學習**」）。關閉課程能看不能學，
        是不同的問題，故在此判定而非改動該函式。

        `open_start_at` 不影響結果：課程能被關閉必然已經發布並開放過。
        """
        assert is_listed_in_my_courses(
            status=COURSE_CLOSED, open_start_at=open_start_at, open_end_at=_NOW + timedelta(days=1), now=_NOW
        )


class TestIsCourseCompleted:
    """完課＝該課程所有未刪除項目皆已完成（US13 AC 1 與 US16 核可前提的閘門）。"""

    def test_全部完成為完課(self) -> None:
        assert is_course_completed(done=3, total=3)

    def test_差一項不算完課(self) -> None:
        assert not is_course_completed(done=2, total=3)

    def test_零項目課程不算完課(self) -> None:
        """按字面定義空課程是 vacuous truth，但那會讓學員一加入就看到問卷入口。

        發布檢核強制 ≥1 章節 + ≥1 教材，已發布課程走不到這裡；真的走到就是資料異常，
        取較保守的那一側。
        """
        assert not is_course_completed(done=0, total=0)

    def test_完成數大於總數仍為完課(self) -> None:
        """`ET_PROGRESS` 的列在項目被刪除後仍留著，理論上可能多於當前項目數。

        `>=` 而非 `==`：若寫 `==`，教師刪掉一個學員已完成的項目就會讓他從完課退回
        進行中，而他實際上該看到的內容一項都沒少。
        """
        assert is_course_completed(done=4, total=3)

    def test_四捨五入為百分之百但未全部完成時不算完課(self) -> None:
        """🔴 這是本函式收 `(done, total)` 而非百分比的唯一理由。

        201 個項目完成 200 個 → `completion_pct` 回 `round(99.5) = 100`。若拿那個 100
        當閘門，最後一項還沒完成問卷入口就開了，而顯示上看起來一切正常——沒有任何
        地方會察覺這個偏差。
        """
        assert completion_pct(200, 201) == 100, "前提：顯示層真的會四捨五入到 100"
        assert not is_course_completed(done=200, total=201)


class TestDeriveCompletionStatus:
    """完課三態由完成/總項目數導出（#284 前置：#274 遺漏之修正）。

    `data-model` §ET_ENROLLMENT 對 `COMPLETION_STATUS` 的說明是「**即時計算**」，
    而在此之前該欄只有加入課程時寫入的 `NOT_STARTED`，沒有任何路徑推進它。
    """

    def test_零進度為未開始(self) -> None:
        assert derive_completion_status(done=0, total=3) == COMPLETION_NOT_STARTED

    def test_全部完成為已完成(self) -> None:
        assert derive_completion_status(done=3, total=3) == COMPLETION_COMPLETED

    @pytest.mark.parametrize(("done", "total"), [(1, 100), (1, 2), (99, 100)])
    def test_中間值為進行中(self, done: int, total: int) -> None:
        assert derive_completion_status(done=done, total=total) == COMPLETION_IN_PROGRESS

    def test_四捨五入為百分之百時仍為進行中(self) -> None:
        """與 `is_course_completed` 同一個邊界——統計與閘門不可分歧。

        若兩者用不同定義，學員會看到卡片標「已完成」卻沒有問卷入口。
        """
        assert derive_completion_status(done=200, total=201) == COMPLETION_IN_PROGRESS

    def test_零項目課程為未開始(self) -> None:
        assert derive_completion_status(done=0, total=0) == COMPLETION_NOT_STARTED


class TestOpenWindowExpired:
    """閱課期間已過 = 視同關閉（#288 SA Q1 裁示 A）。

    在 #288 之前**全後端沒有任何地方讀 `OPEN_END_AT` 做存取判定**——期間結束後課程
    依然可加入、依然留在我的課程清單，而且會一直如此（到期自動轉 `CLOSED` 屬 `ET-16`）。
    """

    def test_期間已過不可加入且與已關閉同碼(self) -> None:
        """對學員而言「已關閉」與「期間已過」是同一件事，故用同一個 `ET_ENROLL_002`。"""
        with pytest.raises(AppError) as exc:
            ensure_course_joinable(course_status=COURSE_PUBLISHED, open_end_at=_NOW - timedelta(seconds=1), now=_NOW)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_ENROLL_002"

    def test_期間內可加入(self) -> None:
        ensure_course_joinable(course_status=COURSE_PUBLISHED, open_end_at=_NOW + timedelta(days=1), now=_NOW)

    def test_起始時間未到仍可加入(self) -> None:
        """🔴 #247 SA Q2 裁示 A。

        本函式**不看起始時間**——那條裁示明訂起始前仍可加入（前端以 `pending_open`
        提示「已加入，課程開放後將出現於清單」）。若 #288 的期間判定順手把起始也納入，
        會靜默推翻它，而 #247 的測試驗的是「可加入」、不會指出是哪一個判定擋的。
        """
        ensure_course_joinable(course_status=COURSE_PUBLISHED, open_end_at=_NOW + timedelta(days=30), now=_NOW)

    def test_訖止為空可加入(self) -> None:
        """為空即資料異常（發布檢核要求必填），取「不要無故擋下」的那一側。"""
        ensure_course_joinable(course_status=COURSE_PUBLISHED, open_end_at=None, now=_NOW)

    def test_期間已過仍留在我的課程清單(self) -> None:
        """US11 AC 9：已關閉課程仍顯示於列表並標示「已關閉」。

        過濾掉會讓學員的歷史紀錄從眼前消失——與該 AC 相反。
        """
        assert is_listed_in_my_courses(
            status=COURSE_PUBLISHED,
            open_start_at=_NOW - timedelta(days=30),
            open_end_at=_NOW - timedelta(seconds=1),
            now=_NOW,
        )
