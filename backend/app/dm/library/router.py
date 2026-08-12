"""文件庫與檢索 API（US3 / DM01，唯讀）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色，無則 403 DM_AUTH_001）；閱覽者結果由 service 套可見性過濾。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.pagination import PagedResponse
from app.dm.deps import DmContext, get_dm_context
from app.dm.library.schemas import Capabilities, ControlledOption, DocumentListItem, DocumentQuery
from app.dm.library.service import LibraryService

router = APIRouter(prefix="/api/dm/library", tags=["dm-library"])
_service = LibraryService()


@router.get("/documents", response_model=PagedResponse[DocumentListItem])
async def search_documents(
    keyword: str | None = Query(default=None, max_length=200),  # 上限防過長 ILIKE（Security LOW）
    category: str | None = Query(default=None),
    author: str | None = Query(default=None, max_length=100),
    tag_ids: list[int] = Query(default=[]),
    func_code: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """多條件搜尋已發布目前版本（含廢止待簽核）；閱覽者套標籤式可見性、發布時間 DESC 分頁。"""
    query = DocumentQuery(
        keyword=keyword,
        category=category,
        author=author,
        tag_ids=tag_ids,
        func_code=func_code,
        date_from=date_from,
        date_to=date_to,
    )
    return await _service.search(db, query=query, ctx=ctx, page=page, limit=limit)


@router.get("/func-options", response_model=list[ControlledOption])
async def func_options(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """系統操作手冊檢索之 func_name 下拉（啟用中）。"""
    return await _service.list_func_options(db)


@router.get("/retrieval-tags", response_model=list[ControlledOption])
async def retrieval_tags(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """檢索標籤下拉（啟用中、含所屬組；不含可見對象/權限標籤）。"""
    return await _service.list_retrieval_tags(db)


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(ctx: DmContext = Depends(get_dm_context)):
    """當前使用者文件庫操作能力（can_create：具編輯者角色才顯示新增文件入口）。"""
    return _service.capabilities(ctx)
