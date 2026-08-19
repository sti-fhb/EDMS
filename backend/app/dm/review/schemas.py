"""簽核中心（US6 / DM04）schema。

待簽核清單 / 明細（新舊版並列）/ 核准並發布 / 退回 / 已完成。回應對齊 spec_us6 FR-001~008。
"""

from datetime import datetime

from pydantic import BaseModel


class PendingItem(BaseModel):
    """待簽核清單列（指派給當前審核者之 PENDING）。"""

    review_id: int
    doc_id: str
    doc_name: str
    category_code: str
    review_type: str  # NEW / NEW_VERSION / OBSOLETE
    version_no: str | None  # 送審版本號（草稿版可能為空）
    submitter_id: str  # 送審者（review.created_user）
    submitter_name: str | None
    submit_date: datetime
    waiting_days: int  # 停留天數（送審至今）


class VersionMeta(BaseModel):
    """版本檔案 metadata（明細之新 / 舊版比對用）。"""

    version_id: int
    version_no: str | None
    file_name: str | None
    file_size: int | None
    file_mime: str | None
    previewable: bool


class ReviewDetail(BaseModel):
    """簽核明細：變更摘要 + 送審檔案（新版本另附目前發布版供比對）。"""

    review_id: int
    doc_id: str
    doc_name: str
    category_code: str
    review_type: str
    change_summary: str | None
    submit_date: datetime
    submitter_id: str
    submitter_name: str | None
    new_version: VersionMeta | None  # 送審版本
    current_version: VersionMeta | None  # 目前發布版（NEW_VERSION 比對；NEW 無）


class RejectReq(BaseModel):
    """退回請求（JSON）。"""

    reason: str


class ApproveResult(BaseModel):
    """核准並發布結果。"""

    published_version_id: int
    notified: int  # 排入 Email 之收件數（0=範本停用 / 無收件）


class RejectResult(BaseModel):
    """退回結果。"""

    review_id: int


class CompletedItem(BaseModel):
    """已完成清單列（當前審核者過往處理）。"""

    review_id: int
    doc_id: str
    doc_name: str
    review_type: str
    status: str  # APPROVED / REJECTED
    version_no: str | None
    complete_date: datetime | None
