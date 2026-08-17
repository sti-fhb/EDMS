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
