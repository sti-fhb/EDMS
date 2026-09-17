"""ET03 線下核可之純業務規則（US16 / #352）。

本檔驗兩件事：**綜合狀態的四態衍生**與**撤銷原因的必填判定**。兩者都不需 DB，故
一律以 unit 驗證——而綜合狀態尤其值得在這一層釘死：它是 `FR-ET-US16-02` 明訂
「MUST NOT 另存狀態欄位」的即時衍生值，整個 ET03 核可欄的呈現都靠它。
"""

import pytest

from app.core.exceptions import AppError
from app.et.approval.rules import (
    STATUS_FAILED,
    STATUS_NOT_ELIGIBLE,
    STATUS_PASSED,
    STATUS_PENDING,
    derive_approval_status,
    ensure_revoke_reason,
)
from app.et.constants import APPROVAL_FAIL, APPROVAL_PASS

pytestmark = pytest.mark.unit


class TestDeriveApprovalStatus:
    """綜合狀態四態（`FR-ET-US16-02`）。

    | 綜合狀態 | 條件 |
    |---|---|
    | 未達核可資格 | 尚未線上完課（**不看核可紀錄**）|
    | 待核可 | 已完課 且（無紀錄 或 已撤銷）|
    | 已通過 | `RESULT = PASS` 且未撤銷 |
    | 未通過 | `RESULT = FAIL` 且未撤銷 |

    ## 為何把「完課 × 紀錄 × 撤銷」八種組合全列出來

    這支函式有兩個獨立的短路點（未完課、已撤銷），各自都能單獨吃掉後面的判斷。
    只測 happy path 的話，其中任一個寫反都仍然會有一半的案例是對的。
    """

    def test_未完課恆為未達核可資格(self) -> None:
        """🔴 未完課時**不看核可紀錄**——連查都不該查。

        `FR-ET-US16-03` 以線上完課為核可前提。這一格若讓紀錄有機會勝出，畫面上會出現
        「進度 75%」卻標著「已通過」的列。
        """
        assert derive_approval_status(completed=False, result=None, is_revoked=False) == STATUS_NOT_ELIGIBLE

    def test_未完課即使已有通過紀錄仍為未達核可資格(self) -> None:
        """⚠️ 這個組合**真的會發生**，不是防禦性測試。

        `FR-ET-US16-09` / 場景 15：教師新增章節會讓已完課學員的完課狀態回退為
        「進行中」，而**核可紀錄不失效**。所以「未完課 + 已通過紀錄」是合法狀態。

        此時顯示「未達核可資格」是對的嗎？是——見 `test_完課回退後核可紀錄仍在`
        對這個取捨的完整說明。
        """
        assert derive_approval_status(completed=False, result=APPROVAL_PASS, is_revoked=False) == STATUS_NOT_ELIGIBLE

    def test_未完課且紀錄已撤銷仍為未達核可資格(self) -> None:
        assert derive_approval_status(completed=False, result=APPROVAL_PASS, is_revoked=True) == STATUS_NOT_ELIGIBLE

    def test_已完課無紀錄為待核可(self) -> None:
        """最常見的一格：完課了、還沒被核可。"""
        assert derive_approval_status(completed=True, result=None, is_revoked=False) == STATUS_PENDING

    def test_已完課且通過為已通過(self) -> None:
        assert derive_approval_status(completed=True, result=APPROVAL_PASS, is_revoked=False) == STATUS_PASSED

    def test_已完課且不通過為未通過(self) -> None:
        """不通過**留紀錄**（`FR-ET-US16-04`），不是回到待核可。"""
        assert derive_approval_status(completed=True, result=APPROVAL_FAIL, is_revoked=False) == STATUS_FAILED

    def test_已撤銷的通過回到待核可(self) -> None:
        """撤銷後綜合狀態 MUST 回「待核可」（`FR-ET-US16-06`）。

        ⚠️ 這裡**不是**回到「未通過」——撤銷是把那次核可作廢，不是改判。
        """
        assert derive_approval_status(completed=True, result=APPROVAL_PASS, is_revoked=True) == STATUS_PENDING

    def test_已撤銷的不通過也回到待核可(self) -> None:
        """撤銷對 PASS 與 FAIL 一視同仁。

        少了這一格，實作寫成「`is_revoked and result == PASS` 才回待核可」也會全綠，
        而被撤銷的不通過會永遠卡在「未通過」、教師再也核可不了他。
        """
        assert derive_approval_status(completed=True, result=APPROVAL_FAIL, is_revoked=True) == STATUS_PENDING


class TestEnsureRevokeReason:
    """撤銷原因必填（`FR-ET-US16-06` / `ET-MSG-ET03-305`）。

    ## 為何不交給 Pydantic 的 `min_length=1`

    `min_length=1` 擋得住空字串，擋不住 `"   "`。而撤銷原因的用途是**事後回答「為什麼
    這筆核可被推翻」**——本表因 `(COURSE_ID, USER_ID)` 唯一而 update 覆寫，前次結果只
    存在 `DP_AUDIT_LOG`，一個全是空白的原因等於沒有。

    另一個理由是錯誤碼：Pydantic 失敗回 `COMMON_422` 且**不回欄位名**（見
    `error-codes.md` §設計原則），前端無從把訊息掛回那個輸入框。
    """

    def test_正常原因原樣回傳去頭尾空白(self) -> None:
        assert ensure_revoke_reason("  考核紀錄登錄錯誤  ") == "考核紀錄登錄錯誤"

    def test_空字串擋下(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_revoke_reason("")
        assert exc.value.error_code == "ET_APPROVAL_005"
        assert exc.value.status_code == 422

    def test_僅空白字元擋下(self) -> None:
        """🔴 這一格是本組測試存在的理由，`min_length=1` 在這裡會放行。"""
        with pytest.raises(AppError) as exc:
            ensure_revoke_reason("   \t\n  ")
        assert exc.value.error_code == "ET_APPROVAL_005"

    def test_None_擋下(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_revoke_reason(None)
        assert exc.value.error_code == "ET_APPROVAL_005"
