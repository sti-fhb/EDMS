"""閱讀統計 KPI API（US13 / UCDM13 / DM10）。

掛 DM 存取閘 `get_dm_context`；清單 / 匯出於 service 層再過 DM_ADMIN 硬閘（FR-002 擋直連）。
唯讀查詢，無寫入、不寫稽核；資料來源 DM_DOC_READ 由 US4（detail）下載時寫入。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dm.deps import DmContext, get_dm_context
from app.dm.kpi.schemas import KpiListResponse
from app.dm.kpi.service import KpiService

router = APIRouter(prefix="/api/dm", tags=["dm-kpi"])
_service = KpiService()


@router.get("/kpi/documents", response_model=KpiListResponse)
async def list_kpi(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊其他 DM 查詢）
    category: str | None = Query(None, max_length=10),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> KpiListResponse:
    """DM10 閱讀統計 KPI（FR-002/003，DM_ADMIN）：逐文件應看/已看/未看/率 + 統計卡，後端分頁。"""
    return await _service.search(db, roles=ctx.roles, keyword=keyword, category=category, page=page, limit=limit)


@router.get("/kpi/documents/export")
async def export_kpi(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),
    category: str | None = Query(None, max_length=10),
) -> Response:
    """匯出當前查詢結果為 CSV（FR-002，DM_ADMIN）。"""
    content = await _service.export_csv(db, roles=ctx.roles, keyword=keyword, category=category)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kpi-reading-stats.csv"'},
    )
