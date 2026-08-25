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


class WithdrawResult(BaseModel):
    """撤回送審結果。

    無 `notified` 欄位：撤回之站內訊息（SUBMIT_WITHDRAWN、CHANNEL=MSG）不經 Email outbox，
    由原審核者之「我的文件動態」（審核者視角 WITHDRAWN）呈現（平台 MSG 設計）。
    """

    review_id: int
    doc_status: str  # 撤回後文件狀態（DRAFT / PUBLISHED）


class ActivityItem(BaseModel):
    """我的文件動態一筆（送審週期事件；前端依 review_type + status + is_overdue 映射顯示標籤）。"""

    review_id: int
    doc_id: str
    doc_name: str
    review_type: str  # NEW / NEW_VERSION / OBSOLETE
    status: str  # PENDING / APPROVED / REJECTED / WITHDRAWN
    submit_date: datetime
    complete_date: datetime | None
    waiting_days: int  # 送審至今停留天數（PENDING 用於催辦判定）
    is_overdue: bool  # PENDING 且停留 ≥ 催辦門檻（審核者視角顯示「催辦中」，AC5）


class ActivityResponse(BaseModel):
    """我的文件動態（角色視角）；兼具兩角色者兩清單皆有值。"""

    author: list[ActivityItem]  # 撰寫者視角（created_user＝我）
    reviewer: list[ActivityItem]  # 審核者視角（assigned_reviewer＝我）


class PersonalAccess(BaseModel):
    """個人專區入口可見性（具編輯者或審核者角色）。"""

    can_access: bool
