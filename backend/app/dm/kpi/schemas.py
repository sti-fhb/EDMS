"""DM10 閱讀統計 KPI schema（US13 / UCDM13）。"""

from pydantic import BaseModel

from app.core.pagination import PageMetaResponse


class KpiQuery(BaseModel):
    """查詢條件：關鍵字（文件名）、分類。"""

    keyword: str | None = None
    category: str | None = None  # CATEGORY_CODE


class KpiDocItem(BaseModel):
    """逐文件閱讀 KPI 列（FR-002/003）。

    rate 為 None 代表應看=0（無對應閱覽者）：前端顯示「—（無對應閱覽者）」、不計入整體平均。
    """

    doc_id: str
    doc_name: str
    category_code: str
    category_name: str | None
    current_version_no: str | None
    should_see: int
    seen: int
    unseen: int
    rate: float | None  # 0~1；應看=0 → None


class KpiSummary(BaseModel):
    """頂部統計卡（AC3a：整體平均排除應看=0 文件）。"""

    total_docs: int
    overall_rate: float | None  # 全部應看>0 文件之平均閱讀率；無可計文件 → None
    below_50_count: int  # 閱讀率 < 50% 之文件數（僅計應看>0 者）


class KpiListResponse(BaseModel):
    """KPI 儀表板回應：逐文件清單（分頁）+ 統計卡摘要。"""

    data: list[KpiDocItem]
    meta: PageMetaResponse
    summary: KpiSummary
