"""文件新增與編輯（US5 / DM03）schema。

寫入型端點以 multipart 收表單欄位 + 單一上傳檔（router 以 Form / UploadFile 宣告），
故此處主要為回應 schema 與下拉項；輸入之欄位級驗證於 router / service。
"""

from pydantic import BaseModel


class CreateResult(BaseModel):
    """新增草稿文件結果。"""

    doc_id: str
    version_id: int


class VersionResult(BaseModel):
    """新增 / 更新草稿版本結果。"""

    version_id: int


class SubmitResult(BaseModel):
    """送簽結果。"""

    review_id: int
    notified: int  # 排入 Email 通知數（0=範本停用 / 僅站內）


class ReviewerItem(BaseModel):
    """指定審核者下拉項（具 DM_REVIEWER 角色、排除自己）。"""

    user_id: str
    user_name: str
