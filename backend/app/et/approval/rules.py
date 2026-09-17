"""線下核可之純業務規則（US16 / #352）。

集中於此而非散在 service：綜合狀態的衍生與撤銷原因的判定都不需 DB，可獨立以 unit
測試驗證，且綜合狀態有兩個呼叫端（核可寫入後的回應、`tracking` 的學員清單）。

錯誤訊息一律不嵌入動態值，對齊 `sti-error-codes`。
"""

from typing import Final

from app.core.exceptions import AppError
from app.et.constants import APPROVAL_FAIL, APPROVAL_PASS

#: 綜合狀態四態（`FR-ET-US16-02`）。
#:
#: ⚠️ **這四個值不是 Lookup，刻意不放進 `constants.LOOKUP_SETS`**：那份對照表對應
#: `data-model` 定義的 10 類代碼表，而綜合狀態 MUST NOT 另存欄位——它是每次查詢由
#: 完課狀態 × 核可紀錄即時導出的回應詞彙，DB 裡不存在這些字串。放進去會讓下一個讀
#: `data-model` 的人去找一個不存在的 `ET_APPROVAL_STATUS` 代碼表。
#:
#: ⚠️ `STATUS_PASSED` 與通知範本代碼 `APPROVAL_PASSED` 只是字面相近，兩者無關：
#: 前者是畫面上的狀態，後者是 `DP_NOTIFY_TEMPLATE` 的一列。
STATUS_NOT_ELIGIBLE: Final = "NOT_ELIGIBLE"
STATUS_PENDING: Final = "PENDING"
STATUS_PASSED: Final = "PASSED"
STATUS_FAILED: Final = "FAILED"

_REASON_REQUIRED = AppError(status_code=422, detail="請填寫撤銷原因", error_code="ET_APPROVAL_006")


def derive_approval_status(*, completed: bool, result: str | None, is_revoked: bool) -> str:
    """由完課狀態與核可紀錄即時導出綜合狀態（`FR-ET-US16-02`：**MUST NOT 另存欄位**）。

    Args:
        completed: 是否已**線上完課**。🔴 必須來自
            `enrollment/rules.is_course_completed(done=, total=)`——不可用
            `progress_pct >= 100`（四捨五入，201 項完成 200 項即回 100），
            更不可讀 `ET_ENROLLMENT.COMPLETION_STATUS`（該欄位只在加入課程時寫入
            `NOT_STARTED`、無任何推進路徑，讀它會讓核可按鈕對每個人都不出現且不報錯）。
        result: 核可結果 `PASS` / `FAIL`；**無核可紀錄時為 `None`**。
        is_revoked: 該筆核可是否已撤銷；無紀錄時傳 `False`。

    Returns:
        `STATUS_NOT_ELIGIBLE` / `STATUS_PENDING` / `STATUS_PASSED` / `STATUS_FAILED`。

    ## 「未完課 + 已有通過紀錄」為何顯示「未達核可資格」

    這個組合是合法的：`FR-ET-US16-09` 明訂教師新增章節致完課回退時**核可紀錄不失效**，
    所以 DB 裡確實會有「進度 75% 且 RESULT=PASS」的狀態。

    此時以完課狀態勝出，是因為這一欄回答的是「**現在**能不能對他做核可動作」——他的
    完課條件已不成立，核可 / 撤銷按鈕都不該出現。紀錄本身沒有被抹掉：補完新章節後這
    一格會自動回到「已通過」（`test_完課回退後核可紀錄仍在` 釘住這件事）。

    反過來讓紀錄勝出的話，畫面會出現「進度 75%」配「已通過」的列，而教師無從判斷那是
    舊核可還是系統算錯。
    """
    if not completed:
        return STATUS_NOT_ELIGIBLE
    if result is None or is_revoked:
        return STATUS_PENDING
    return STATUS_PASSED if result == APPROVAL_PASS else STATUS_FAILED


def is_active_approval(*, result: str | None, is_revoked: bool) -> bool:
    """是否為**有效**核可紀錄（存在且未撤銷）。

    批次核可據此跳過（SA 裁示 2026-09-17 Q2 = A）。

    🔴 **`is_revoked` 那半段不可省**：省了會把「已撤銷」也算成有效紀錄，於是
    `FR-ET-US16-06` 的「撤銷後可重新核可」整條路徑會靜默死掉——教師按下通過，
    系統回「已跳過」，而那位學員的狀態是「待核可」。
    """
    return result is not None and not is_revoked


def ensure_revoke_reason(reason: str | None) -> str:
    """撤銷原因必填，回傳去除頭尾空白後的內容（`FR-ET-US16-06`）。

    Args:
        reason: 使用者輸入的原因。

    Returns:
        去頭尾空白後的原因。

    Raises:
        AppError: 422 `ET_APPROVAL_006`，原因為 `None`、空字串或**全為空白**。

    ## 為何不交給 Pydantic 的 `min_length=1`

    兩個理由：

    1. `min_length=1` 放行 `"   "`。撤銷原因的用途是事後回答「為什麼這筆核可被推翻」
       ——本表因 `(COURSE_ID, USER_ID)` 唯一而以 update 覆寫，前次結果只存在
       `DP_AUDIT_LOG`，一個全是空白的原因等於沒有。
    2. Pydantic 驗證失敗回 `COMMON_422` 且**不回欄位名**（`error-codes.md` §設計原則），
       前端無從把 `ET-MSG-ET03-305` 掛回那個輸入框。
    """
    if reason is None or not reason.strip():
        raise _REASON_REQUIRED
    return reason.strip()


__all__ = [
    "APPROVAL_FAIL",
    "APPROVAL_PASS",
    "STATUS_FAILED",
    "STATUS_NOT_ELIGIBLE",
    "STATUS_PASSED",
    "STATUS_PENDING",
    "derive_approval_status",
    "ensure_revoke_reason",
    "is_active_approval",
]
