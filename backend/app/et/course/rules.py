"""ET 課程 / 章節之純業務規則（#202）。

集中於此而非散在 service：這些規則不需 DB、可獨立以 unit test 驗證，且多處呼叫
（如 `ensure_owner` 於編輯 / 刪除 / 章節操作皆用）。Service 負責取資料與寫入，
判斷交給本模組。

錯誤訊息一律不嵌入動態值（使用者 ID、課程名稱等），對齊 `sti-error-codes`
——防 log injection，亦不洩漏他人資料是否存在。
"""

from datetime import datetime

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED


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


def ensure_closable(status: str) -> None:
    """僅已發布課程可關閉（US11 AC 2 / FR-ET-US11-01）。

    **草稿不可關閉**：草稿沒有學員、沒有邀請碼，關閉它沒有語意——要移除草稿走既有的
    `DELETE`（`ensure_deletable` 明訂僅草稿可刪）。兩者恰好互補。

    **已關閉不可再關閉**：不是「重複操作無害」，而是狀態機沒有那條邊；讓它通過會再寫
    一次 `CLOSED_AT`，把「最近一次關閉時間」覆蓋成第二次點擊的時間。

    Raises:
        AppError: 409 `ET_COURSE_006`。
    """
    if status != COURSE_PUBLISHED:
        raise AppError(status_code=409, detail="僅已發布課程可關閉", error_code="ET_COURSE_006")


def ensure_reopenable(status: str) -> None:
    """僅已關閉課程可再開課（US11 AC 8）。

    與 `ensure_closable` **刻意分成兩個錯誤碼**：兩者的下一步不同（「這門課還沒發布」
    → 去發布；「這門課已經關了」→ 去再開課），共用單一碼會讓前端只能顯示一句模稜
    兩可的訊息。措辭比照 `ET_COURSE_005`（「僅草稿課程可刪除，已發布課程請改用關閉」）
    那種「這個狀態不給做，請改用另一個動作」的形狀。

    Raises:
        AppError: 409 `ET_COURSE_007`。
    """
    if status != COURSE_CLOSED:
        raise AppError(status_code=409, detail="僅已關閉課程可再開課", error_code="ET_COURSE_007")


def is_effectively_closed(*, status: str, open_end_at: datetime | None, now: datetime) -> bool:
    """課程對學員是否**視同關閉**（#288 SA Q1 裁示 A）。

    「已關閉」或「已發布但閱課期間已過」兩者皆是——後者是本函式補上的缺口。

    ## 這支函式補上的是一個實際存在的缺口

    `spec_us11` 場景 7、FR-ET-US11-03 與 `data-model` §ET_COURSE 業務規則（「`now >
    OPEN_END_AT` 視同關閉」）三處都要求「應用層即時判定」，但在本 issue 之前**全後端
    沒有任何地方讀 `OPEN_END_AT` 做存取判定**——閱課期間結束後，課程照常可加入、可累積
    進度、可作答、可填問卷，而且會一直如此（到期自動轉 `CLOSED` 屬 `ET-16`，未實作）。

    ## 🔴 為何**只看訖止、不看起始**

    「起始時間未到」與「視同關閉」是兩件不同的事，混在一起會推翻兩條既有決定：

    1. **#247 SA Q2 裁示 A：起始時間未到之課程仍可加入。** 若本函式要求「起始已到」，
       `ensure_course_joinable` 會開始擋下起始前的加入，直接違反該裁示。
    2. **草稿與起始未到都不是「關閉」。** `learning` 以本函式的結果驅動「此課程目前
       關閉中」的唯讀提示；把草稿（教師預覽）或起始未到判成關閉，教師與學員會看到一句
       與事實不符的提示。

    起始時間的可見性判定已由 `publish_rules.is_visible_to_student` 承載（`my_courses`
    清單用），本函式不重複它。

    ## 呼叫端一律以「與 `CLOSED` 相同」處理

    回 `True` 時各處的行為與 `STATUS = CLOSED` 完全一致——邀請碼失效、進度寫入 409、
    問卷不可填、ET05 唯讀回看。**不可**改成「視同不存在」：已關閉課程仍要留在我的課程
    清單、仍可唯讀回看（AC 9 / 10），把它當成不可見會讓學員的歷史紀錄從眼前消失。

    ⚠️ **`attempt/` 目前未接上本函式**——該目錄由 #280 進行中（footprint 保護）。故期間
    已過時仍可開新作答，與其餘四處不一致；已列為 #288 的 follow-up。
    """
    if status == COURSE_CLOSED:
        return True
    # 訖止為空代表「沒有結束日」——不該因為一個缺失的欄位去關掉一門教師沒有要求關閉
    # 的課程。已發布課程必有起訖（發布檢核 `BLOCK_NO_SCHEDULE`），為空即資料異常。
    return status == COURSE_PUBLISHED and open_end_at is not None and now > open_end_at


def ensure_reopen_schedule(*, open_end_at: datetime, now: datetime) -> None:
    """再開課的新訖止時間須**嚴格晚於當下**（#288 SA Q3 裁示 A）。

    ## 為何這裡檢核「對比當下」，而 `schemas._end_after_start` 刻意不檢核

    `_CourseFields` 有一條 2026-08-24 的裁示：「起始須 ≥ 當下」不在後端檢核，因為
    **已發布課程的起始時間必然落在過去**，無條件檢核會讓教師之後編輯該課程時因為沿用
    原值而永遠存不了檔。

    那個理由在再開課**不存在**——再開課的兩個時間是 FR-ET-US11-09 明訂「強制重新設定」
    的，沒有沿用舊值的問題。而若不檢核，直呼 API 就能造出「已發布但期間已過」的課程：
    教師端看到「已發布」，學員端卻被 `is_effectively_closed` 判為視同關閉而進不去，
    **狀態自相矛盾，且沒有任何地方會察覺**。

    **只檢核訖止、不檢核起始**：起始允許落在過去——「補開一段已經開始的期間」是合理
    操作（教師想讓學員從上週就能看），與 2026-08-24 裁示的方向一致。

    Raises:
        AppError: 422 `ET_COURSE_008`（訊息即 `ET-MSG-ET02-204`）。
    """
    if open_end_at <= now:
        raise AppError(
            status_code=422,
            detail="請重新設定一組新的起訖時間後方可再開課",
            error_code="ET_COURSE_008",
        )


def resequence(ordered_ids: list[int]) -> dict[int, int]:
    """把「完整順序陣列」轉為 `{id: SORT_ORDER}`，自 1 起連續編號。

    Args:
        ordered_ids: 依欲呈現順序排列之章節 ID。

    Returns:
        章節 ID → 新 `SORT_ORDER` 之對照。
    """
    return {chapter_id: index for index, chapter_id in enumerate(ordered_ids, start=1)}


def _ensure_reorder_complete(*, current_ids: set[int], requested: list[int], detail: str, error_code: str) -> None:
    """重排請求須涵蓋且僅涵蓋現有子項——章節與項目共用之核心判定。

    採「完整順序陣列」而非相對移動（上移 / 下移），避免並行編輯下的順序漂移：
    相對移動在兩人同時操作時會疊加出非預期結果，完整陣列則是最後寫入者的完整意圖。

    **長度與集合都要檢查**：`[1, 1, 2]` 之集合等同 `{1, 2}`，僅比對集合會漏掉重複；
    集合比對則擋下缺漏與夾帶他人資料 ID 的越權嘗試。
    """
    if len(requested) != len(set(requested)) or set(requested) != current_ids:
        raise AppError(status_code=422, detail=detail, error_code=error_code)


def ensure_reorder_complete(*, current_ids: set[int], requested: list[int]) -> None:
    """章節重排：清單須涵蓋且僅涵蓋該課程之現有章節。

    Raises:
        AppError: 422 `ET_CHAPTER_002`，清單有重複、缺漏或含非本課程之章節。
    """
    _ensure_reorder_complete(
        current_ids=current_ids,
        requested=requested,
        detail="重排清單與課程章節不一致",
        error_code="ET_CHAPTER_002",
    )


def ensure_item_reorder_complete(*, current_ids: set[int], requested: list[int]) -> None:
    """項目重排：清單須涵蓋且僅涵蓋該**章節**之現有項目（#203）。

    與章節重排同一判定、不同錯誤碼——前端需靠 `error_code` 分辨是哪一層的重排失敗，
    共用單一代碼會使「章節重排壞了」與「項目重排壞了」在 UI 上無從區隔。

    Raises:
        AppError: 422 `ET_ITEM_002`，清單有重複、缺漏或含非本章節之項目。
    """
    _ensure_reorder_complete(
        current_ids=current_ids,
        requested=requested,
        detail="重排清單與章節項目不一致",
        error_code="ET_ITEM_002",
    )
