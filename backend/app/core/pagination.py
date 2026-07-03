"""
分頁 helper：封裝 count query + offset/limit 邏輯，回傳統一的 data/meta 格式。

使用範例（service 層）：
    result = await paginate(db, stmt, page=page, limit=limit, schema=CourseResponse)
    return result
"""

from typing import Any, Generic, TypedDict, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError

SchemaT = TypeVar("SchemaT", bound=BaseModel)
DataT = TypeVar("DataT", bound=BaseModel)

__all__ = ["paginate", "PaginatedResult", "PageMeta", "PagedResponse", "PageMetaResponse", "MAX_LIMIT"]

# 每次請求最多可取得的筆數上限，防止 DoS 攻擊
MAX_LIMIT = 100


class PageMeta(TypedDict):
    """分頁 meta 資訊。"""

    total: int
    page: int
    limit: int
    total_pages: int


class PageMetaResponse(BaseModel):
    """分頁 meta 回應（Pydantic 版，供 FastAPI response_model 使用）。"""

    total: int
    page: int
    limit: int
    total_pages: int


class PagedResponse(BaseModel, Generic[DataT]):
    """通用分頁回應 schema，供 FastAPI response_model 使用。

    用法：response_model=PagedResponse[CourseResponse]
    """

    data: list[DataT]
    meta: PageMetaResponse


class PaginatedResult(TypedDict, Generic[SchemaT]):
    """paginate() 的回傳格式。data 的型別與傳入的 schema 一致。"""

    data: list[SchemaT]
    meta: PageMeta


async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    page: int,
    limit: int,
    schema: type[SchemaT],
) -> PaginatedResult[SchemaT]:
    """
    分頁查詢 helper。

    Args:
        db:     AsyncSession
        stmt:   已套用 where / order_by 的 SQLAlchemy Select，
                不得包含 offset/limit（由此函式負責套用）。
        page:   頁碼，1-based（必須 >= 1）。
        limit:  每頁筆數（必須 >= 1，上限 MAX_LIMIT=100）。
        schema: Pydantic schema class，用於序列化 ORM 物件。

    Returns:
        {
            "data": [序列化後的物件列表],
            "meta": { total, page, limit, total_pages }
        }

    Raises:
        AppError(422): page < 1、limit < 1 或 limit > MAX_LIMIT 時。
    """
    if page < 1:
        raise AppError(status_code=422, detail="page 必須 >= 1", error_code="COMMON_002")
    if limit < 1:
        raise AppError(status_code=422, detail="limit 必須 >= 1", error_code="COMMON_003")
    if limit > MAX_LIMIT:
        raise AppError(status_code=422, detail=f"limit 不得超過 {MAX_LIMIT}", error_code="COMMON_004")

    # COUNT 查詢（不套 offset/limit）
    count_stmt = select(func.count()).select_from(stmt.subquery())
    raw = await db.scalar(count_stmt)
    total: int = raw if raw is not None else 0

    # total=0 時明確回傳 0，不依賴除法隱含行為
    total_pages = (total + limit - 1) // limit if total > 0 else 0

    # page 超出範圍時直接回空，避免傳送無意義的大 offset 至資料庫
    if total > 0 and page > total_pages:
        return {
            "data": [],
            "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages},
        }

    # 資料查詢（套 offset/limit）
    offset = (page - 1) * limit
    result = await db.execute(stmt.offset(offset).limit(limit))
    items = list(result.scalars().all())

    return {
        "data": [schema.model_validate(item) for item in items],
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        },
    }
