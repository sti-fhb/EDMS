"""已廢止文件查詢 API（US10 / UCDM08 / DM06）。

掛 DM 存取閘 `get_dm_context`；清單 / 匯出於 service 層再過 DM_ADMIN 硬閘（FR-001 擋直連）。
唯讀查詢，無寫入、不寫稽核。read-only 詳細頁重用 US4（前端導向 /dm/documents/{docId}），本模組不含。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.pagination import PagedResponse
from app.dm.deps import DmContext, get_dm_context
from app.dm.obsolete_archive.schemas import ObsoleteAccess, ObsoleteDocItem, ObsoleteQuery
from app.dm.obsolete_archive.service import ObsoleteArchiveService

router = APIRouter(prefix="/api/dm", tags=["dm-obsolete-archive"])
_service = ObsoleteArchiveService()


@router.get("/obsolete-archive/access", response_model=ObsoleteAccess)
async def obsolete_access(ctx: DmContext = Depends(get_dm_context)) -> ObsoleteAccess:
    """DM06 入口可見性（FR-001）：具 DM_ADMIN 才顯示側欄項；供前端逐項閘（非 403）。"""
    return _service.get_access(ctx.roles)


@router.get("/obsolete-archive/documents", response_model=PagedResponse[ObsoleteDocItem])
async def list_obsolete(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊 library/review，Security LOW）
    category: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> PagedResponse[ObsoleteDocItem]:
    """已廢止文件查詢（FR-002/003，DM_ADMIN）：關鍵字 / 分類 / 廢止日期區間，後端分頁。"""
    query = ObsoleteQuery(keyword=keyword, category=category, date_from=date_from, date_to=date_to)
    return await _service.search(db, query=query, roles=ctx.roles, page=page, limit=limit)


@router.get("/obsolete-archive/documents/export")
async def export_obsolete(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(None, max_length=200),  # 上限防過長 ILIKE（對齊 library/review，Security LOW）
    category: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Response:
    """匯出當前查詢結果為 CSV（FR-005，DM_ADMIN）。"""
    query = ObsoleteQuery(keyword=keyword, category=category, date_from=date_from, date_to=date_to)
    content = await _service.export_csv(db, query=query, roles=ctx.roles)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="obsolete-documents.csv"'},
    )
