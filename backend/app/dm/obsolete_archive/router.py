"""已廢止文件查詢 API（US10 / UCDM08 / DM03）。

掛 DM 存取閘 `get_dm_context`；清單 / 匯出於 service 層再過 DM_ADMIN 硬閘（FR-001 擋直連）。
唯讀查詢，無寫入、不寫稽核。read-only 詳細頁重用 US4（前端導向 /dm/documents/{docId}），本模組不含。
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
from app.dm.deps import DmContext, get_dm_admin_context, get_dm_context
from app.dm.obsolete_archive.schemas import ObsoleteDocItem, ObsoleteQuery
from app.dm.obsolete_archive.service import ObsoleteArchiveService

# 對應 DM_CATEGORY.CATEGORY_CODE 之 VARCHAR(10)（與 dm/library/router.py 一致）
_CODE_MAX_LEN = 10

router = APIRouter(prefix="/api/dm", tags=["dm-obsolete-archive"])
_service = ObsoleteArchiveService()

#: 匯出限流（#833 B4），門檻理由見 `core/rate_limit.EXPORT_USER_RATE_MAX`。
_EXPORT_SCOPE = "dm-obsolete-archive-export"
_export_user_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_USER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_export_ip_limiter = SlidingWindowRateLimiter(max_requests=EXPORT_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

# 入口可見性改用共用 GET /api/dm/admin-access（US11 A' 收斂）；本模組不再提供 /obsolete-archive/access。


@router.get("/obsolete-archive/documents", response_model=PagedResponse[ObsoleteDocItem])
async def list_obsolete(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊 library/review，Security LOW）
    category: str | None = Query(None, max_length=_CODE_MAX_LEN),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PagedResponse[ObsoleteDocItem]:
    """已廢止文件查詢（FR-002/003，DM_ADMIN）：關鍵字 / 分類 / 廢止日期區間，後端分頁。"""
    query = ObsoleteQuery(keyword=keyword, category=category, date_from=date_from, date_to=date_to)
    return await _service.search(db, query=query, roles=ctx.roles, page=page, limit=limit)


@router.get(
    "/obsolete-archive/documents/export",
    # 先過 DM 管理者閘再限流：非管理者在閘口 403、不佔名額（理由見 `get_dm_admin_context`）。
    dependencies=[
        Depends(get_dm_admin_context),
        Depends(rate_limit_by_user(_export_user_limiter, _EXPORT_SCOPE)),
        Depends(rate_limit_by_ip(_export_ip_limiter, _EXPORT_SCOPE)),
        Depends(limit_concurrent_exports),
    ],
)
async def export_obsolete(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊 library/review，Security LOW）
    category: str | None = Query(None, max_length=_CODE_MAX_LEN),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Response:
    """匯出當前查詢結果為 CSV（FR-005，DM_ADMIN）。"""
    query = ObsoleteQuery(keyword=keyword, category=category, date_from=date_from, date_to=date_to)
    content = await _service.export_csv(db, query=query, roles=ctx.roles)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={**NO_STORE_HEADERS, "Content-Disposition": 'attachment; filename="obsolete-documents.csv"'},
    )
