"""
分頁 helper：封裝 count query + offset/limit 邏輯，回傳統一的 data/meta 格式。

使用範例（service 層）：
    result = await paginate(db, stmt, page=page, limit=limit, schema=CourseResponse)
    return result
"""

from typing import Any, Generic, TypedDict, TypeVar

from pydantic import BaseModel
from sqlalchemy import CompoundSelect, Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError

SchemaT = TypeVar("SchemaT", bound=BaseModel)
DataT = TypeVar("DataT", bound=BaseModel)

__all__ = [
    "paginate",
    "paginate_rows",
    "PaginatedResult",
    "RowPage",
    "PageMeta",
    "PagedResponse",
    "PageMetaResponse",
    "MAX_LIMIT",
]

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

    # page 超出範圍時直接回空，避免傳送無意義的大 offset 至資料庫。
    #
    # 🔴 `max(total_pages, 1)` 的 1 是為了 `total == 0`（#511）：此時 `total_pages` 為 0，
    # 原條件寫 `total > 0 and page > total_pages`，整條被跳過 ⇒ 超大 page 會原封不動算成
    # offset 送進 DB，超出 PostgreSQL `int8` 即拋例外 → 500。而 `page` 在 router 層只有
    # `ge=1`、沒有上限，Python 的 int 又是任意精度。
    #
    # ⛔ 不要改成在各 router 的 `page` 加 `le=`：那要求**每個新端點的作者都記得加**，
    # 漏加不會有任何訊號。守在這裡則是所有列表自動涵蓋。
    #
    # 空清單的**第一頁**仍照常查詢（`1 > max(0, 1)` 為假）——那是常態路徑，不能一起擋掉。
    if page > max(total_pages, 1):
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


class RowPage(TypedDict):
    """`paginate_rows()` 的回傳格式——`data` 是**原始 Row**，由呼叫端自行映射成 schema。"""

    data: list[Row[Any]]
    meta: PageMeta


async def paginate_rows(
    db: AsyncSession,
    stmt: Select[Any] | CompoundSelect,
    page: int,
    limit: int,
) -> RowPage:
    """回傳原始 Row 的分頁 helper（#464）——供**多欄查詢**（如 `UNION ALL`）使用。

    ## 為何不用 `paginate()`

    `paginate()` 以 `result.scalars().all()` 取值，**只拿第一欄**。聯集查詢的結果是多欄
    Row、不是 ORM 實體，交給它會**靜默只剩第一欄**——不報錯，只是資料不見了。

    ## 🔴 與 `paginate()` 的驗證與 count 邏輯是**刻意的重複**

    不把兩支抽成共用內部函式，是因為那等於改 `paginate()` 的實作——而它被全專案每一個
    列表使用。⛔ 兩支的門檻、錯誤碼、早退規則若要改，**必須一起改**；
    `tests/unit/test_core_pagination_rows.py` 對**兩支**斷言同一組錯誤碼與早退行為，
    只改一支時會紅。

    ⚠️ 本段原寫「`paginate()` **沒有任何針對它的直接測試**」——自 #511 起**只對其餘行為成立**：
    越界早退與輸入驗證兩支都有直接的 unit test，其餘（真實 count、序列化、實際 offset 值）
    仍只由各功能的 integration test 間接覆蓋。抽共用函式的門檻因此**降低但未消失**。

    Args:
        db:    AsyncSession
        stmt:  已套 where / order_by 的 `Select` 或 `CompoundSelect`（`UNION` 等）。
               不得包含 offset/limit。⚠️ 排序必須**決定性**（含唯一的 tiebreak），
               否則翻頁時同一列可能重複出現或被漏掉。
        page:  頁碼，1-based（必須 >= 1）。
        limit: 每頁筆數（必須 >= 1，上限 MAX_LIMIT）。

    Returns:
        `{"data": [Row, ...], "meta": {total, page, limit, total_pages}}`

    Raises:
        AppError(422): page < 1、limit < 1 或 limit > MAX_LIMIT 時（錯誤碼同 `paginate()`）。
    """
    if page < 1:
        raise AppError(status_code=422, detail="page 必須 >= 1", error_code="COMMON_002")
    if limit < 1:
        raise AppError(status_code=422, detail="limit 必須 >= 1", error_code="COMMON_003")
    if limit > MAX_LIMIT:
        raise AppError(status_code=422, detail=f"limit 不得超過 {MAX_LIMIT}", error_code="COMMON_004")

    count_stmt = select(func.count()).select_from(stmt.subquery())
    raw = await db.scalar(count_stmt)
    total: int = raw if raw is not None else 0
    total_pages = (total + limit - 1) // limit if total > 0 else 0

    # 早退規則與 `paginate()` **逐字相同**（含 `max(total_pages, 1)` 的理由，見該處註解）。
    # ⛔ 兩支必須一起改；`tests/unit/test_core_pagination_rows.py` 對兩支斷言同一組早退行為。
    if page > max(total_pages, 1):
        return {"data": [], "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

    offset = (page - 1) * limit
    result = await db.execute(stmt.offset(offset).limit(limit))
    return {
        "data": list(result.all()),
        "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages},
    }
