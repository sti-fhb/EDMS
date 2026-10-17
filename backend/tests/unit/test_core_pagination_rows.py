"""`core/pagination.paginate_rows()`（#464）——回傳原始 Row 的分頁 helper。

## 為何另開一支，而不是改 `paginate()`

`paginate()` 以 `result.scalars().all()` 取值——**只拿第一欄**。ET04 的查詢是兩個來源的
`UNION ALL`，結果是多欄 Row、不是 ORM 實體，`scalars()` 會**靜默只取第一欄**。

⛔ **不改 `paginate()` 的取值方式**：它被全專案每一個列表使用，而當時（#464）本專案
**沒有任何針對它的直接測試**（只透過各功能的 integration test 間接驗）——改它的內部就是
在沒有護欄的情況下動全系統。

⚠️ 上一句自 **#511** 起只對**其餘行為**成立：輸入驗證與越界早退兩支都有直接 unit test
（就在本檔），其餘（真實 count、序列化、實際 offset 值）仍只間接覆蓋。

## 為何這組是 unit

- **輸入驗證**在碰 DB **之前**就拋出，傳 `db=None` 即可驗。
- **越界早退**（#511）只取決於 `count` 的結果，用一個假 DB（`_CountOnlyDb`）即可驗，
  而且驗得比 integration **更準**——它斷言的是「那個 offset 有沒有被送進 DB」，
  真 DB 反而只看得到「回了空清單」，修法前後都一樣。

真實 count、序列化與實際 offset 值仍由
`tests/integration/et/test_et_approval_query.py` 以真資料覆蓋（那才是 `paginate_rows` 的消費者）。

## 🔴 錯誤碼與早退規則必須與 `paginate()` 完全一致

兩支的驗證與早退邏輯是**刻意的重複**（見上：不改 `paginate()` 的取值方式）。這組測試對
**兩支**斷言同一組錯誤碼與早退行為——日後有人只改其中一支的門檻、代碼或早退條件，
這裡會紅，而不是讓兩支列表 API 對同一個輸入有不同反應。
"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.pagination import MAX_LIMIT, paginate, paginate_rows
from app.et.course.models import EtCourse

pytestmark = pytest.mark.unit

_STMT = select(EtCourse.course_id)


class _Dummy:
    """`paginate()` 需要一個 schema 參數；驗證階段用不到它。"""

    @classmethod
    def model_validate(cls, _obj):  # pragma: no cover - 驗證失敗時不會走到
        raise AssertionError("驗證失敗時不該進入序列化")


@pytest.mark.parametrize(
    ("page", "limit", "code"),
    [
        (0, 20, "COMMON_002"),
        (1, 0, "COMMON_003"),
        (1, MAX_LIMIT + 1, "COMMON_004"),
    ],
)
async def test_非法輸入在碰資料庫之前就擋下(page: int, limit: int, code: str) -> None:
    """`db=None`：若驗證之前就碰了 DB，這裡會拋 `AttributeError` 而不是 `AppError`。"""
    with pytest.raises(AppError) as exc:
        await paginate_rows(None, _STMT, page, limit)  # type: ignore[arg-type]
    assert exc.value.status_code == 422
    assert exc.value.error_code == code


@pytest.mark.parametrize(("page", "limit"), [(0, 20), (1, 0), (1, MAX_LIMIT + 1)])
async def test_錯誤碼與既有_paginate_完全一致(page: int, limit: int) -> None:
    """🔴 兩支的驗證是刻意的重複——只改一支時這條會紅。"""
    with pytest.raises(AppError) as rows_exc:
        await paginate_rows(None, _STMT, page, limit)  # type: ignore[arg-type]
    with pytest.raises(AppError) as orm_exc:
        await paginate(None, _STMT, page, limit, _Dummy)  # type: ignore[arg-type]
    assert rows_exc.value.error_code == orm_exc.value.error_code
    assert rows_exc.value.detail == orm_exc.value.detail


# ── 越界早退（#511）────────────────────────────────────────────────

# 超出 PostgreSQL `int8` 範圍。`page` 在 router 層只有 `ge=1`、沒有上限，而 Python 的 int
# 是任意精度 ⇒ 這個值會原封不動被算成 offset。
_HUGE_PAGE = 99_999_999_999_999_999_999


class _EmptyResult:
    """空結果：`paginate_rows` 走 `.all()`、`paginate` 走 `.scalars().all()`，兩條都回空。"""

    def all(self) -> list[object]:
        return []

    def scalars(self) -> "_EmptyResult":
        return self


class _CountOnlyDb:
    """假 DB：`scalar()` 回固定 total，`execute()` 只記錄「被呼叫過」。

    🔴 **斷言的是 `execute` 有沒有被呼叫，不是回傳值。** 修法前後兩者回的都是空清單
    （小的越界 page 送進 DB 也只是查無資料），差別在於**那個 offset 到不到得了 DB**——
    #511 的 500 正是 PostgreSQL 收到超出 `int8` 的 offset 才發生的。驗回傳值會是
    「通過中的測試在斷言錯的契約」。
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.execute_calls = 0

    async def scalar(self, _stmt: object) -> int:
        return self.total

    async def execute(self, _stmt: object) -> _EmptyResult:
        self.execute_calls += 1
        return _EmptyResult()


async def _call_rows(db: object, page: int, limit: int) -> dict:
    return await paginate_rows(db, _STMT, page, limit)  # type: ignore[arg-type]


async def _call_orm(db: object, page: int, limit: int) -> dict:
    return await paginate(db, _STMT, page, limit, _Dummy)  # type: ignore[arg-type]


_BOTH = pytest.mark.parametrize(("helper", "call"), [("paginate_rows", _call_rows), ("paginate", _call_orm)])


@_BOTH
async def test_清單為空時超大_page_不把_offset_送進資料庫(helper: str, call) -> None:
    """#511：`total == 0` 時早退條件原本不成立，超大 page 會讓 offset 溢位 `int8` → 500。"""
    db = _CountOnlyDb(total=0)
    result = await call(db, _HUGE_PAGE, 20)
    assert db.execute_calls == 0, f"{helper}：超大 offset 仍被送進資料庫"
    assert result["data"] == []
    assert result["meta"] == {"total": 0, "page": _HUGE_PAGE, "limit": 20, "total_pages": 0}


@_BOTH
async def test_清單為空時第一頁仍照常查詢(helper: str, call) -> None:
    """⚠️ 反向探針：修法不得把「空清單的第一頁」也一起擋掉——那才是常態路徑。"""
    db = _CountOnlyDb(total=0)
    result = await call(db, 1, 20)
    assert db.execute_calls == 1, f"{helper}：空清單的第一頁被誤擋，連查都沒查"
    assert result["data"] == []


@_BOTH
@pytest.mark.parametrize(
    ("page", "expect_execute"),
    [(3, 1), (4, 0)],
    ids=["最後一頁仍查詢", "超過最後一頁早退"],
)
async def test_有資料時的早退行為未變(helper: str, call, page: int, expect_execute: int) -> None:
    """迴歸護欄：`total=25, limit=10` ⇒ `total_pages=3`，第 3 頁查、第 4 頁早退（修法前後一致）。"""
    db = _CountOnlyDb(total=25)
    await call(db, page, 10)
    assert db.execute_calls == expect_execute, f"{helper}：第 {page} 頁的早退行為與修法前不同"
