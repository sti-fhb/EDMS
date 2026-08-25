"""ET 課程 / 章節之純業務規則（#202）。

集中於此而非散在 service：這些規則不需 DB、可獨立以 unit test 驗證，且多處呼叫
（如 `ensure_owner` 於編輯 / 刪除 / 章節操作皆用）。Service 負責取資料與寫入，
判斷交給本模組。

錯誤訊息一律不嵌入動態值（使用者 ID、課程名稱等），對齊 `sti-error-codes`
——防 log injection，亦不洩漏他人資料是否存在。
"""

from app.core.exceptions import AppError
from app.et.constants import COURSE_DRAFT


def ensure_owner(*, owner_id: str, actor_id: str) -> None:
    """僅課程擁有者可編輯（`spec.md` §擁有權判定）。

    他人課程僅可閱覽——讀取端不呼叫本函式，改以回傳之 `is_owner` 讓前端呈現唯讀。

    Args:
        owner_id: 課程之 `OWNER_ID`。
        actor_id: 當前操作者 `USER_ID`。

    Raises:
        AppError: 403 `ET_COURSE_002`，操作者非擁有者。
    """
    if owner_id != actor_id:
        raise AppError(status_code=403, detail="僅課程擁有者可編輯", error_code="ET_COURSE_002")


def ensure_tag_change_allowed(status: str, *, current: set[int], desired: set[int]) -> None:
    """草稿可自由增刪標籤；**非草稿僅可新增、不可移除**（FR-ET-US3-02）。

    「不可移除」涵蓋 `PUBLISHED` 與 `CLOSED`——關閉只是暫時狀態（可再開課），
    既有學員仍持有該課程，放寬移除會使「哪些標籤曾觸發自動邀請」失去可追溯性。

    Args:
        status: 課程當前狀態（`ET_COURSE_STATUS`）。
        current: 課程現有之 `TAG_ID` 集合。
        desired: 本次欲設定之 `TAG_ID` 集合。

    Raises:
        AppError: 422 `ET_COURSE_003`，非草稿課程嘗試移除既有標籤。
    """
    if status != COURSE_DRAFT and (current - desired):
        raise AppError(status_code=422, detail="已發布課程不可移除既有標籤", error_code="ET_COURSE_003")


def ensure_deletable(status: str) -> None:
    """僅草稿課程可刪除（SA 裁示 Q1，#202）。

    已發布 / 已關閉課程改用 US11 之「關閉」——關閉可逆且保留學員 enrollment 與
    學習紀錄；允許刪除會與關閉語意重疊，且直接摧毀學員資料。

    Raises:
        AppError: 422 `ET_COURSE_005`，非草稿課程嘗試刪除。
    """
    if status != COURSE_DRAFT:
        raise AppError(status_code=422, detail="僅草稿課程可刪除，已發布課程請改用關閉", error_code="ET_COURSE_005")


def resequence(ordered_ids: list[int]) -> dict[int, int]:
    """把「完整順序陣列」轉為 `{id: SORT_ORDER}`，自 1 起連續編號。

    Args:
        ordered_ids: 依欲呈現順序排列之章節 ID。

    Returns:
        章節 ID → 新 `SORT_ORDER` 之對照。
    """
    return {chapter_id: index for index, chapter_id in enumerate(ordered_ids, start=1)}


def ensure_reorder_complete(*, current_ids: set[int], requested: list[int]) -> None:
    """重排請求須涵蓋且僅涵蓋該課程之現有章節。

    採「完整順序陣列」而非相對移動（上移 / 下移），避免並行編輯下的順序漂移：
    相對移動在兩人同時操作時會疊加出非預期結果，完整陣列則是最後寫入者的完整意圖。

    **長度與集合都要檢查**：`[1, 1, 2]` 之集合等同 `{1, 2}`，僅比對集合會漏掉重複；
    集合比對則擋下缺漏與夾帶他人課程章節 ID 的越權嘗試。

    Raises:
        AppError: 422 `ET_CHAPTER_002`，清單有重複、缺漏或含非本課程之章節。
    """
    if len(requested) != len(set(requested)) or set(requested) != current_ids:
        raise AppError(status_code=422, detail="重排清單與課程章節不一致", error_code="ET_CHAPTER_002")
