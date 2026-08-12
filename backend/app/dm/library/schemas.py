"""文件庫與檢索（US3 / DM01）schema。

讀取型：查詢參數（多條件檢索）與清單回應。清單僅呈現「已發布」目前版本（含廢止待簽核），
呈現欄位對齊 spec_us3 FR-003（文件名 / 分類 / 發布日期 / 作者 / 檢索標籤；手冊類另附 func_name）。
"""

from datetime import date, datetime

from pydantic import BaseModel


class DocumentListItem(BaseModel):
    """文件庫清單列（已發布目前版本）。"""

    doc_id: str
    doc_name: str
    category_code: str
    category_name: str
    published_date: datetime | None
    author_id: str  # 撰寫者 USER_ID（DM_DOCUMENT.CREATED_USER）
    author_name: str | None  # 撰寫者姓名（唯讀 join DP_USER；查無 None）
    func_code: str | None  # 僅「系統操作手冊」有值
    func_name: str | None
    tags: list[str]  # 檢索標籤名稱（灰字頓號呈現；不含可見對象/權限標籤）


class ControlledOption(BaseModel):
    """受控清單下拉選項（func_name / 檢索標籤）。"""

    code: str  # func_code；檢索標籤為 TAG_ID 字串
    name: str
    group_code: str | None = None  # 檢索標籤所屬組（MODULE / NATURE / LEGAL），供前端分組


class DocumentQuery(BaseModel):
    """文件庫搜尋條件（皆選填；多標籤 AND）。"""

    keyword: str | None = None
    category: str | None = None
    author: str | None = None
    tag_ids: list[int] = []
    func_code: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class Capabilities(BaseModel):
    """當前使用者於文件庫之操作能力（供前端決定入口顯示）。"""

    can_create: bool  # 具編輯者角色（DM_EDITOR）→ 顯示「新增文件」入口（FR-006 / AC8）
