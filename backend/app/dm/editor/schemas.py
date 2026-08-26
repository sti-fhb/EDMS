"""文件新增與編輯（US5 / DM03）schema。

寫入型端點以 multipart 收表單欄位 + 單一上傳檔（router 以 Form / UploadFile 宣告），
故此處主要為回應 schema、送簽 JSON 請求與表單受控下拉；輸入之欄位級檢核於 service。
"""

from pydantic import BaseModel


class CreateResult(BaseModel):
    """新增草稿文件結果。"""

    doc_id: str
    version_id: int
    previewable: bool  # 上傳檔是否可線上預覽（False=Office 等 → 前端出橘色警示條 DM-MSG-DM03-002）


class VersionResult(BaseModel):
    """新增草稿版本結果。"""

    version_id: int
    previewable: bool


class SubmitReq(BaseModel):
    """送簽請求（JSON）。"""

    version_id: int
    assigned_reviewer: str


class SubmitResult(BaseModel):
    """送簽結果。"""

    review_id: int
    notified: int  # 排入 Email 通知數（0=範本停用 / 僅站內）


class ReviewerItem(BaseModel):
    """指定審核者下拉項（具 DM_REVIEWER 角色、排除自己）。"""

    user_id: str
    user_name: str


class EditorDocTags(BaseModel):
    """文件現有標籤（TAG_ID 字串），供編輯模式預帶可改。"""

    audience_ids: list[str]
    retrieval_ids: list[str]


class DraftMeta(BaseModel):
    """續編草稿之編輯器 meta（author-scoped；供 DRAFT-status 文件亦可載，不經 DM02 詳細端點）。

    父文件 DRAFT（首版草稿）→ `name_editable=True`（名稱可改，Q1=A）；父文件 PUBLISHED（新版本草稿）
    → `name_editable=False`（名稱唯讀，比照 FR-003）。分類綁 DOC_ID 一律唯讀，不提供可編輯性旗標。
    """

    doc_id: str
    doc_name: str
    category_code: str
    category_name: str
    func_code: str | None
    func_name: str | None
    doc_status: str  # 父文件狀態（DRAFT / PUBLISHED）
    name_editable: bool
    draft_version_id: int  # 本人現有之 DRAFT 版本（續編對象）
    version_no: str | None
    change_summary: str | None
    file_name: str | None
    file_size: int | None
    previewable: bool
    assigned_reviewer: str | None  # 退回 / 撤回草稿之前次指定審核者（供預帶；未送審為 None）


class OptionItem(BaseModel):
    """表單受控下拉項。"""

    code: str  # 分類碼 / func_code / 標籤 TAG_ID 字串
    name: str
    group_code: str | None = None  # 檢索標籤所屬組（MODULE / NATURE / LEGAL），供前端分組


class EditorOptions(BaseModel):
    """DM03 表單一次載入之受控下拉集合。"""

    categories: list[OptionItem]
    funcs: list[OptionItem]  # 系統操作手冊之關聯作業項目
    audiences: list[OptionItem]  # 可見對象（含「全體」）
    retrieval_tags: list[OptionItem]  # 檢索標籤（分組）
