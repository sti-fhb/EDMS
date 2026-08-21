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
    """最新更新公告列（近 30 天已發布之版本）。"""

    doc_id: str
    doc_name: str
    category_code: str
    version_no: str
    change_summary: str | None
    published_date: datetime
    author_name: str | None
    kind: str  # NEW（新增首版）/ NEW_VERSION（新版本）
