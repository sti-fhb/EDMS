"""文件庫與檢索 API（US3 / DM01，唯讀）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色，無則 403 DM_AUTH_001）；閱覽者結果由 service 套可見性過濾。
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.pagination import PagedResponse
from app.dm.deps import DmContext, get_dm_context
from app.dm.library.schemas import Capabilities, ControlledOption, DocumentListItem, DocumentQuery
from app.dm.library.service import LibraryService

router = APIRouter(prefix="/api/dm/library", tags=["dm-library"])
_service = LibraryService()

# 對應 DM_CATEGORY.CATEGORY_CODE / DM_FUNC.FUNC_CODE 之 VARCHAR(10)
_CODE_MAX_LEN = 10
_TAG_IDS_MAX = 50

#: 單一 tag_id 之值域。`DM_TAG.TAG_ID` 為 BIGINT，而 Pydantic 的 `int` 是任意精度——不界住的話，
#: 超出 int64 的值會通過驗證、到 asyncpg 編碼期才拋 `DataError`，無人攔截即 500（#483）。
TagId = Annotated[int, Field(ge=1, le=2**63 - 1)]


@router.get("/documents", response_model=PagedResponse[DocumentListItem])
async def search_documents(
    keyword: str | None = Query(default=None, max_length=200),  # 上限防過長 ILIKE（Security LOW）
    category: str | None = Query(default=None, max_length=_CODE_MAX_LEN),
    author: str | None = Query(default=None, max_length=100),
    # 長度與值域都要界：長度擋的是查詢成本放大（1000 個值的 `IN` 要在 correlated EXISTS 內
    # 逐列評估），值域擋的是超出 int64 導致 asyncpg 編碼期未攔截的 500。50 遠高於實際標籤總數。
    tag_ids: Annotated[list[TagId], Query(max_length=_TAG_IDS_MAX)] = [],  # noqa: B006
    func_code: str | None = Query(default=None, max_length=_CODE_MAX_LEN),
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


@router.get("/category-options", response_model=list[ControlledOption])
async def category_options(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """文件分類下拉（啟用中）；DM01 / DM03 / DM06 共用，取代前端寫死的 4 筆常數。"""
    return await _service.list_category_options(db)


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
