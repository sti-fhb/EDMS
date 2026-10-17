"""個人專區（US9 / UCDM09 / DM04）schema。"""

from datetime import datetime

from pydantic import BaseModel

# 草稿分類（依該版本之 DM_REVIEW 歷史）：未送審 / 被退回 / 已撤回
DraftKind = str  # "unsubmitted" | "rejected" | "withdrawn"


class DraftItem(BaseModel):
    """草稿匣一筆（DRAFT 版本 + 三類標記）。"""

    version_id: int
    doc_id: str
    doc_name: str
    version_no: str | None
    change_summary: str | None
    category_code: str
    kind: DraftKind
    updated_date: datetime | None
    doc_status: str  # 父文件狀態（OBSOLETE 時前端灰掉「繼續編輯」、僅允許刪除）


class WithdrawResult(BaseModel):
    """撤回送審結果。

    無 `notified` 欄位：撤回之站內訊息（SUBMIT_WITHDRAWN、CHANNEL=MSG）不經 Email outbox，
    由原審核者之「我的文件動態」（審核者視角 WITHDRAWN）呈現（平台 MSG 設計）。
    """

    review_id: int
    doc_status: str  # 撤回後文件狀態（DRAFT / PUBLISHED）


class ActivityEvent(BaseModel):
    """我的文件動態一筆「狀態變動事件」（一次送審週期依其進度展開為 送審 → 核准/退回/撤回 多列事件，
    各帶其發生時間；前端依 review_type + status + event_kind + 視角映射中文標籤，時間新→舊排序）。"""

    review_id: int
    doc_id: str
    doc_name: str
    review_type: str  # NEW / NEW_VERSION / OBSOLETE
    status: str  # 該送審週期終態 / 現態：PENDING / APPROVED / REJECTED / WITHDRAWN
    event_kind: str  # "submitted"（送審 / 發起廢止）| "resolved"（核准 / 退回 / 撤回 之結果）
    event_time: datetime  # 該事件發生時間（submitted＝送審時間、resolved＝完成時間）
    #: 僅 PENDING 之 submitted 事件：停留 ≥ 催辦門檻。**兩個視角都吃這個欄位**，但字樣不同：
    #: 撰寫者視角顯「逾期未審」/「廢止逾期未審」、審核者視角顯「催辦中」（AC5）。
    #:
    #: ⚠️ 撰寫者那半是 #395 D-2 才補上的（在那之前卡 1 天與卡 100 天字樣完全相同，撰寫者
    #: 沒有任何訊號知道該撤回重送）。本註解原先只寫審核者視角，會讓要查撰寫者視角的人
    #: 直接把這個欄位排除在考慮外——而「催辦」一詞**只存在於審核者端**，照它 grep 在
    #: 撰寫者端一無所獲。兩處字樣見 `frontend/src/dm/personal/schemas.ts` 的
    #: `authorEventLabel` 與 `reviewerEventLabel`。
    is_overdue: bool
    #: 退回原因（#554 / #657 / #679）。**僅 `event_kind="resolved"` 且 `status="REJECTED"`
    #: 時有值**（**含廢止退回**），其餘為 None。來源為 `DM_REVIEW.REJECT_REASON`。
    #:
    #: ⚠️ #679 之前讀的是 `REASON`，而該欄對 OBSOLETE 是申請人寫的廢止申請原因，故當時必須
    #: 多一個 `review_type != "OBSOLETE"` 的排除——代價是廢止退回的原因完全看不到。
    #:
    #: 背景：DOC_REJECT / OBS_REJECT 範本內文原帶「退回原因：{reason}」，改為站內（MSG）後
    #: 那封信不再寄出。若不在此帶出，`DM_REVIEW.REASON` 會寫入卻**沒有任何讀取端**——
    #: 撰寫者只知道「被退回」、不知道「為什麼」。
    #:
    #: ⚠️ `submitted` 事件一律給 None：同一個 `REASON` 欄位在 OBSOLETE 的送審事件上是
    #: 「廢止申請原因」（申請人自己寫的），對他不是新資訊，混進來只會讓兩種語意糊在一起。
    reason: str | None
    party_name: str | None  # 撰寫者視角＝指定審核者姓名；審核者視角＝送審者姓名
    #: 對造人帳號不可達之原因（#395 D-2）：`None` 可達／`"DISABLED"` 已停用／`"NOT_FOUND"` 查無帳號。
    #:
    #: ⚠️ 兩類**刻意不併成一句**——補救動作不同（查無要修資料、停用要換審核者），與催辦 log 的
    #: 三分法同一判準（`dm/review/center_service.py`）。
    #:
    #: 撰寫者視角下它回答的是「我的審核者還能不能處理這件事」：停用者登不進系統，那筆送審
    #: 永遠卡著，而撰寫者本來就能撤回重送——缺的只是**沒有任何東西告訴他該撤回**。
    party_unreachable: str | None


class ActivityResponse(BaseModel):
    """我的文件動態（依當下角色呈現視角）；兼具兩角色者兩清單皆有值。只呈現與本人送審週期相關之事件。"""

    author: list[ActivityEvent]  # 撰寫者視角（我送審之文件狀態變動）
    reviewer: list[ActivityEvent]  # 審核者視角（指派給我之送審狀態變動）


class PersonalAccess(BaseModel):
    """個人專區入口可見性（具編輯者或審核者角色）。"""

    can_access: bool
    #: 是否顯示**草稿匣頁籤**（#657）。`spec_us9` FR-001 寫的是「草稿匣（**編輯者**）」。
    #:
    #: 與 `can_access` 刻意分開、不可合併：前者決定**側欄入口**（編輯者 **或** 審核者皆可進
    #: 個人專區看我的文件動態），後者決定**頁內的草稿匣頁籤**（僅編輯者）。建草稿的端點全掛
    #: `_ensure_editor`，純審核者不可能有草稿，那個頁籤對他永遠是空的。
    #:
    #: ⚠️ 依**當前角色**判定：角色被撤銷的前編輯者，其既有草稿仍在 DB 但介面上看不到。
    #: 這是已裁示的取捨（2026-10-15），不是漏考慮——與 #627 的「角色撤了但歷史指派還在」
    #: 同一形狀，此處選擇以當前角色為準。
    can_draft: bool
