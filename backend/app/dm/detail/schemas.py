"""文件詳細頁瀏覽（US4 / DM02）schema。

讀取型：詳細頁（標題 + 資訊面板 + 目前版檔案 meta + 操作能力 + 廢止資訊）與版本歷程。
描述性 metadata 統一於資訊面板（不與標題重複，FR-001）。
"""

from datetime import datetime

from pydantic import BaseModel


class FileMeta(BaseModel):
    """目前發布版之檔案 metadata（供檔案區呈現 / 預覽下載判定）。"""

    version_id: int
    file_name: str
    file_mime: str
    file_size: int
    uploaded_at: datetime | None  # 版本建立時間
    previewable: bool  # PDF / 圖片可預覽；Office 僅下載


class ObsoleteInfo(BaseModel):
    """已廢止文件之廢止資訊（read-only banner 用；取自 DM_REVIEW 廢止類已核准週期）。"""

    review_id: int  # 廢止送審週期 ID（供下載廢止附件 /dm/reviews/{id}/obsolete-file）
    obsolete_time: datetime | None  # 核准廢止時間（COMPLETE_DATE）
    applicant_id: str  # 申請人 USER_ID（DM_REVIEW.CREATED_USER）
    applicant_name: str | None
    approver_name: str | None
    reason: str | None
    has_attachment: bool  # 廢止附件（OBSOLETE_FILE_*）是否存在
    attachment_name: str | None  # 廢止附件原始檔名（下載時之檔名；無附件為 None）


class DetailResponse(BaseModel):
    """文件詳細頁（目前發布版）。"""

    # 標題列（識別 + 狀態）
    doc_id: str
    doc_name: str
    status: str  # PUBLISHED / PENDING_OBSOLETE / OBSOLETE
    current_version_no: str | None
    # 資訊面板（描述性 metadata）
    category_code: str
    category_name: str
    author_id: str
    author_name: str | None
    published_date: datetime | None
    approver_id: str | None
    approver_name: str | None
    approve_time: datetime | None  # 即發布時間
    tags: list[str]  # 檢索標籤名稱（灰字頓號；不含可見對象）
    func_code: str | None  # 僅系統操作手冊
    func_name: str | None
    # 目前版檔案 + 操作能力
    file: FileMeta | None
    is_editor: bool  # 具 DM_EDITOR → 呈現編輯/廢止入口（送審中時灰階、非隱藏）
    is_admin: bool  # 具 DM_ADMIN → 已廢止 read-only 下可下載無法預覽（Office）版本（US10 稽核）
    can_edit: bool  # DM_EDITOR 且無進行中 PENDING 送審週期 → 入口可點
    edit_lock_reason: str | None  # 入口失效原因（送審中 / 廢止待簽核）；可點時為 None
    is_obsolete: bool  # STATUS=OBSOLETE → read-only 模式
    obsolete_info: ObsoleteInfo | None


class VersionItem(BaseModel):
    """版本歷程列（含歷史版本）。"""

    version_id: int
    version_no: str
    change_summary: str
    file_name: str  # 下載檔名（與文件檔案區一致，避免存檔名不符）
    author_id: str
    author_name: str | None
    approver_name: str | None
    published_date: datetime | None
    is_current: bool  # 目前發布版（可下載）；否則僅預覽
    previewable: bool
