"""文件變更歷程查詢 API（US11 / UCDM10 / DM05）。

掛 DM 存取閘 `get_dm_context`；清單 / 匯出於 service 層再過 DM_ADMIN 硬閘（FR-001 擋直連）。
唯讀查詢，無寫入、不寫稽核；資料來源 DM_CHANGE_LOG 由 US6/US8 核准時寫入。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.http_cache import NO_STORE_HEADERS
from app.core.pagination import PagedResponse
from app.core.rate_limit import (
    EXPORT_IP_RATE_MAX,
    EXPORT_USER_RATE_MAX,
    RATE_WINDOW_SECONDS,
    SlidingWindowRateLimiter,
    limit_concurrent_exports,
    rate_limit_by_ip,
    rate_limit_by_user,
)
from app.dm.change_log.schemas import ChangeLogEntry, ChangeLogQuery, Operation
from app.dm.change_log.service import ChangeLogService
from app.dm.deps import DmContext, get_dm_admin_context, get_dm_context

router = APIRouter(prefix="/api/dm", tags=["dm-change-log"])
_service = ChangeLogService()

#: 匯出限流（#833 B4），門檻理由見 `core/rate_limit.EXPORT_USER_RATE_MAX`。
_EXPORT_SCOPE = "dm-change-log-export"
_export_user_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_USER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_export_ip_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)


@router.get("/change-log/entries", response_model=PagedResponse[ChangeLogEntry])
async def list_entries(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊 obsolete_archive）
    operation: Operation | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PagedResponse[ChangeLogEntry]:
    """變更歷程查詢（FR-002/003，DM_ADMIN）：日期 / 申請人or核准人 / 操作類型，後端分頁。"""
    query = ChangeLogQuery(keyword=keyword, operation=operation, date_from=date_from, date_to=date_to)
    return await _service.search(db, query=query, roles=ctx.roles, page=page, limit=limit)


@router.get(
    "/change-log/entries/export",
    # 先過 DM 管理者閘再限流：非管理者在閘口 403、不佔名額（理由見 `get_dm_admin_context`）。
    dependencies=[
        Depends(get_dm_admin_context),
        Depends(rate_limit_by_user(_export_user_limiter, _EXPORT_SCOPE)),
        Depends(rate_limit_by_ip(_export_ip_limiter, _EXPORT_SCOPE)),
        Depends(limit_concurrent_exports),
    ],
)
async def export_entries(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),
    operation: Operation | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Response:
    """匯出當前查詢結果為 CSV（FR-004，DM_ADMIN）。"""
    query = ChangeLogQuery(keyword=keyword, operation=operation, date_from=date_from, date_to=date_to)
    content = await _service.export_csv(db, query=query, roles=ctx.roles)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={**NO_STORE_HEADERS, "Content-Disposition": 'attachment; filename="change-log.csv"'},
    )
