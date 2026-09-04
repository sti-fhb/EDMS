"""Email 邀請之純業務規則（US8 / #273）。

教師是把 Email 從通訊錄、Excel、通訊軟體貼進來的，格式什麼樣子都有——換行、逗號、
分號、全形逗號、大小寫混雜、前後空白、同一個人貼兩次。這些在到達 DB 之前就要收斂，
否則同一個人會收到兩封信、或建出兩列 `ET_INVITATION`。
"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.invitation.rules import MAX_EMAILS_PER_REQUEST, ensure_invitable, parse_emails

pytestmark = pytest.mark.unit


class TestParseEmails:
    def test_換行分隔(self) -> None:
        assert parse_emails("a@x.gov.tw\nb@x.gov.tw") == ["a@x.gov.tw", "b@x.gov.tw"]

    def test_逗號分隔(self) -> None:
        assert parse_emails("a@x.gov.tw,b@x.gov.tw") == ["a@x.gov.tw", "b@x.gov.tw"]

    def test_分號與全形逗號一併視為分隔(self) -> None:
        """從 Excel / 通訊軟體貼進來的清單常見這兩種分隔。"""
        assert parse_emails("a@x.gov.tw；b@x.gov.tw，c@x.gov.tw") == ["a@x.gov.tw", "b@x.gov.tw", "c@x.gov.tw"]

    def test_混用分隔與多餘空白(self) -> None:
        raw = "  a@x.gov.tw ,\n\n b@x.gov.tw \r\n"
        assert parse_emails(raw) == ["a@x.gov.tw", "b@x.gov.tw"]

    def test_正規化為小寫(self) -> None:
        """`DP_USER.EMAIL` 以小寫儲存；不正規化會使「找得到帳號」的比對落空。"""
        assert parse_emails("A@X.GOV.TW") == ["a@x.gov.tw"]

    def test_去重且保留首次出現順序(self) -> None:
        """同一人貼兩次只該收到一封信；順序保留讓預覽的「第 1 筆」符合教師的預期。"""
        assert parse_emails("b@x.gov.tw, a@x.gov.tw, B@x.gov.tw") == ["b@x.gov.tw", "a@x.gov.tw"]

    def test_空白輸入回空清單而非報錯(self) -> None:
        """「還沒輸入」不是錯誤——由呼叫端決定要不要擋。"""
        assert parse_emails("   \n  ") == []

    @pytest.mark.parametrize(
        "raw",
        [
            "not-an-email",
            "a@",
            "@x.gov.tw",
            "a b@x.gov.tw",
            "a@x",
            "a@@x.gov.tw",
        ],
    )
    def test_格式不合法一律拒絕(self, raw: str) -> None:
        with pytest.raises(AppError) as exc:
            parse_emails(raw)
        assert exc.value.error_code == "ET_INVITE_003"

    def test_超過單次上限拒絕(self) -> None:
        raw = ",".join(f"u{i}@x.gov.tw" for i in range(MAX_EMAILS_PER_REQUEST + 1))
        with pytest.raises(AppError) as exc:
            parse_emails(raw)
        assert exc.value.error_code == "ET_INVITE_003"

    def test_恰好等於上限可通過(self) -> None:
        raw = ",".join(f"u{i}@x.gov.tw" for i in range(MAX_EMAILS_PER_REQUEST))
        assert len(parse_emails(raw)) == MAX_EMAILS_PER_REQUEST

    def test_上限與平台收件人上限一致(self) -> None:
        """教師看到的上限與平台 `NotifyService._MAX_RECIPIENTS` 同值，避免兩套數字。"""
        from app.dp.notify.service import _MAX_RECIPIENTS

        assert MAX_EMAILS_PER_REQUEST == _MAX_RECIPIENTS

    def test_去重後才計算上限(self) -> None:
        """貼了 60 筆但其實只有 2 個不同的人，不該被擋。"""
        raw = ",".join(["a@x.gov.tw", "b@x.gov.tw"] * 30)
        assert parse_emails(raw) == ["a@x.gov.tw", "b@x.gov.tw"]


class TestEnsureInvitable:
    """AC 1：僅已發布課程可邀請學員。"""

    def test_已發布可邀請(self) -> None:
        ensure_invitable(course_status=COURSE_PUBLISHED)

    @pytest.mark.parametrize("status", [COURSE_DRAFT, COURSE_CLOSED])
    def test_草稿與已關閉不可邀請(self, status: str) -> None:
        with pytest.raises(AppError) as exc:
            ensure_invitable(course_status=status)
        assert exc.value.error_code == "ET_INVITE_004"
        assert exc.value.status_code == 422
