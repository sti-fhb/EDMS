"""系統儀表板（US7 / DM00）schema。回應對齊 spec_us7 FR-002 / FR-003。"""

from datetime import datetime

from pydantic import BaseModel


class CategoryStat(BaseModel):
    """單一分類之已發布目前版本統計。"""

    category_code: str
    category_name: str
    count: int


class DashboardStats(BaseModel):
    """各類型文件總數（4 內建分類 + 總計）。"""

    items: list[CategoryStat]
    total: int


class AnnouncementItem(BaseModel):
    """最新更新公告列（最新 N 筆已發布之版本；不設時間窗，#758）。"""

    doc_id: str
    doc_name: str
    # 保留理由同 `personal/schemas.py` 的 `DraftItem`：對外相容，前端已無消費者。
    # ⛔ 與同檔 `CategoryStat.category_code`（StatCard 的 React key）不是同一回事，別混。
    category_code: str
    category_name: str  # 分類中文名稱（查表取目前值，#735）；前端公告列顯示此欄
    version_no: str
    change_summary: str | None
    published_date: datetime
    author_name: str | None
    kind: str  # NEW（新增首版）/ NEW_VERSION（新版本）
