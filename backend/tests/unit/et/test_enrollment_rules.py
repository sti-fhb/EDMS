"""ET04 加入課程與我的課程清單之純業務規則（US4 / #247）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.enrollment.rules import (
    INVITATION_CODE_LENGTH,
    ensure_course_joinable,
    ensure_not_removed,
    is_listed_in_my_courses,
    normalize_invitation_code,
)

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
        ensure_course_joinable(course_status=COURSE_PUBLISHED)

    def test_已關閉課程被擋(self) -> None:
        """AC 9 / ET-MSG-ET04-002：邀請碼於關閉期間失效、再開課後恢復有效。

        故判定依據是**課程當前狀態**，不是碼本身存不存在。
        """
        with pytest.raises(AppError) as exc:
            ensure_course_joinable(course_status=COURSE_CLOSED)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_ENROLL_002"

    def test_草稿課程視為查無(self) -> None:
        """邀請碼於發布時才產生，草稿課程照理取不到碼。

        真的走到這裡只可能是資料異常；回 404（而非「關閉中」）以免向未受邀者
        洩漏一門尚未發布之課程的存在。
        """
        with pytest.raises(AppError) as exc:
            ensure_course_joinable(course_status=COURSE_DRAFT)
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
        assert is_listed_in_my_courses(status=COURSE_PUBLISHED, open_start_at=_NOW - timedelta(days=1), now=_NOW)

    def test_起始時間未到不可見(self) -> None:
        """AC 4：起始時間未到之課程不顯示於清單。"""
        assert not is_listed_in_my_courses(status=COURSE_PUBLISHED, open_start_at=_NOW + timedelta(minutes=1), now=_NOW)

    def test_恰好等於起始時間即可見(self) -> None:
        """邊界沿用 `publish_rules.is_visible_to_student` 之 `now >= open_start_at`。"""
        assert is_listed_in_my_courses(status=COURSE_PUBLISHED, open_start_at=_NOW, now=_NOW)

    def test_起始時間為空不可見(self) -> None:
        assert not is_listed_in_my_courses(status=COURSE_PUBLISHED, open_start_at=None, now=_NOW)

    def test_草稿不可見(self) -> None:
        assert not is_listed_in_my_courses(status=COURSE_DRAFT, open_start_at=_NOW - timedelta(days=1), now=_NOW)

    @pytest.mark.parametrize("open_start_at", [_NOW - timedelta(days=1), _NOW + timedelta(days=1), None])
    def test_已關閉課程一律可見(self, open_start_at: datetime | None) -> None:
        """AC 5 / AC 13：已關閉課程顯示「已關閉」標示、可唯讀回看。

        這是 `ET-4` 與 `publish_rules.is_visible_to_student` 的分歧點——後者對
        `CLOSED` 回 False（它問的是「能否**開始學習**」）。關閉課程能看不能學，
        是不同的問題，故在此判定而非改動該函式。

        `open_start_at` 不影響結果：課程能被關閉必然已經發布並開放過。
        """
        assert is_listed_in_my_courses(status=COURSE_CLOSED, open_start_at=open_start_at, now=_NOW)
