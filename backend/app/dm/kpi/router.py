"""閱讀統計 KPI API（US13 / UCDM13 / DM06）。

掛 DM 存取閘 `get_dm_context`；清單 / 匯出於 service 層再過 DM_ADMIN 硬閘（FR-002 擋直連）。
唯讀查詢，無寫入、不寫稽核；資料來源 DM_DOC_READ 由 US4（detail）下載時寫入。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.http_cache import NO_STORE_HEADERS
from app.core.rate_limit import (
    EXPORT_IP_RATE_MAX,
    EXPORT_USER_RATE_MAX,
    RATE_WINDOW_SECONDS,
    SlidingWindowRateLimiter,
    limit_concurrent_exports,
    rate_limit_by_ip,
    rate_limit_by_user,
)
from app.dm.deps import DmContext, get_dm_admin_context, get_dm_context
from app.dm.kpi.schemas import KpiListResponse
from app.dm.kpi.service import KpiService

router = APIRouter(prefix="/api/dm", tags=["dm-kpi"])
_service = KpiService()

#: 匯出限流（#833 B4），門檻理由見 `core/rate_limit.EXPORT_USER_RATE_MAX`。
_EXPORT_SCOPE = "dm-kpi-export"
_export_user_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_USER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_export_ip_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)


@router.get("/kpi/documents", response_model=KpiListResponse)
async def list_kpi(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊其他 DM 查詢）
    category: str | None = Query(None, max_length=10),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> KpiListResponse:
    """DM06 閱讀統計 KPI（FR-002/003，DM_ADMIN）：逐文件應看/已看/未看/率 + 統計卡，後端分頁。"""
    return await _service.search(db, roles=ctx.roles, keyword=keyword, category=category, page=page, limit=limit)


@router.get(
    "/kpi/documents/export",
    # 先過 DM 管理者閘再限流：非管理者在閘口 403、不佔名額（理由見 `get_dm_admin_context`）。
    dependencies=[
        Depends(get_dm_admin_context),
        Depends(rate_limit_by_user(_export_user_limiter, _EXPORT_SCOPE)),
        Depends(rate_limit_by_ip(_export_ip_limiter, _EXPORT_SCOPE)),
        Depends(limit_concurrent_exports),
    ],
)
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
        headers={**NO_STORE_HEADERS, "Content-Disposition": 'attachment; filename="kpi-reading-stats.csv"'},
    )
