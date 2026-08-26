"""個人專區（US9 / UCDM09 / DM07）schema。"""

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
    is_overdue: bool  # 僅 PENDING 之 submitted 事件：停留 ≥ 催辦門檻（審核者視角顯「催辦中」，AC5）
    party_name: str | None  # 撰寫者視角＝指定審核者姓名；審核者視角＝送審者姓名


class ActivityResponse(BaseModel):
    """我的文件動態（依當下角色呈現視角）；兼具兩角色者兩清單皆有值。只呈現與本人送審週期相關之事件。"""

    author: list[ActivityEvent]  # 撰寫者視角（我送審之文件狀態變動）
    reviewer: list[ActivityEvent]  # 審核者視角（指派給我之送審狀態變動）


class PersonalAccess(BaseModel):
    """個人專區入口可見性（具編輯者或審核者角色）。"""

    can_access: bool
