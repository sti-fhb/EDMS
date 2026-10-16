"""文件新增與編輯（US5 / DM08）schema。

寫入型端點以 multipart 收表單欄位 + 單一上傳檔（router 以 Form / UploadFile 宣告），
故此處主要為回應 schema、送簽 JSON 請求與表單受控下拉；輸入之欄位級檢核於 service。
"""

from pydantic import BaseModel


class CreateResult(BaseModel):
    """新增草稿文件結果。"""

    doc_id: str
    version_id: int
    previewable: bool  # 上傳檔是否可線上預覽（False=Office 等 → 前端出橘色警示條 DM-MSG-DM08-002）


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
    notified: int  # 排入 Email 通知數（0=範本停用 / 僅站內 / 排入失敗，見 DmNotifier）


class ReviewerItem(BaseModel):
    """指定審核者下拉項（具 DM_REVIEWER 角色、排除自己）。"""

    user_id: str
    user_name: str


class AudiencePair(BaseModel):
    """可見對象之 (單位, 職位) 配對（#437）；ID 為 `DM_TAG.TAG_ID` 字串。"""

    unit_id: str
    audience_id: str


class EditorDocTags(BaseModel):
    """文件現有標籤，供編輯模式預帶可改。"""

    audience_pairs: list[AudiencePair]
    retrieval_ids: list[str]
    #: `tag_id`（字串）→ 標籤名稱，**涵蓋上述所有 id、含已被管理者停用者**（#624）。
    #:
    #: 為何需要：`get_editor_options` 只回**啟用中**的選項，而本預帶**刻意不濾**
    #: `is_enabled`（濾掉等於讓使用者不知情地把既有標籤送掉——#602 要消滅的形狀）。
    #: 兩者相減 ⇒ 停用標籤的 id 在表單裡、卻不在選項裡，前端 `options.find(...)` 落空，
    #: **該值在畫面上是隱形的**；送出時後端回 `DM_DOC_010`，使用者卻看不到要改哪一格。
    #:
    #: 帶名稱（而非「是否停用」旗標）是因為前端要顯示的就是「哪個值」，而它連名字都沒有；
    #: 一個欄位同時解決檢索標籤與可見對象（單位 / 職位）三處。
    #: ⛔ **只涵蓋本回應已出現的 id，不得擴充為完整標籤目錄**：本端點掛 `_ensure_editor`，
    #: 編輯者本來就看得到這些文件；但回出整份含停用的清單會從「這份文件用了什麼」變成
    #: 「系統裡有哪些受控選項」，那是另一件事（啟用中的目錄另有 `/dm/editor/options`）。
    tag_names: dict[str, str]


class DraftMeta(BaseModel):
    """續編草稿之編輯器 meta（author-scoped；供 DRAFT-status 文件亦可載，不經 DM07 詳細端點）。

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
    """DM08 表單一次載入之受控下拉集合。"""

    categories: list[OptionItem]
    funcs: list[OptionItem]  # 系統操作手冊之關聯作業項目
    audiences: list[OptionItem]  # 可見對象之職位（含通用值「全體」）
    units: list[OptionItem]  # 可見對象之單位（含通用值「全單位」＝不限單位，#437）
    retrieval_tags: list[OptionItem]  # 檢索標籤（分組）


class UploadLimits(BaseModel):
    """目前生效的上傳限制（#455）。

    ⚠️ **值一律由 `file_store.resolve_upload_limits` 解析**，與上傳驗證同源——另寫一支
    就會分岔，而分岔的表徵是「選得到卻傳不上去」（或相反）。

    Attributes:
        max_mb: 單檔上限（MB）。
        allowed_extensions: 允許的副檔名，**不含點**、全小寫、已排序。
            排序是為了回應穩定——未排序時同一組設定在不同查詢可能給出不同順序，
            而前端的文案會跟著變，看起來像設定被改過。
    """

    max_mb: int
    allowed_extensions: list[str]
