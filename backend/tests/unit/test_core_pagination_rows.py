"""`core/pagination.paginate_rows()`（#464）——回傳原始 Row 的分頁 helper。

## 為何另開一支，而不是改 `paginate()`

`paginate()` 以 `result.scalars().all()` 取值——**只拿第一欄**。ET04 的查詢是兩個來源的
`UNION ALL`，結果是多欄 Row、不是 ORM 實體，`scalars()` 會**靜默只取第一欄**。

⛔ **不改 `paginate()`**：它被全專案每一個列表使用，而本專案**沒有任何針對它的直接測試**
（只透過各功能的 integration test 間接驗）——改它的內部就是在沒有護欄的情況下動全系統。

## 為何這組是 unit

三條輸入驗證在碰 DB **之前**就拋出，傳 `db=None` 即可驗。實際的 count / offset / 早退
行為由 `tests/integration/et/test_et_approval_query.py` 以真資料覆蓋（那才是它的消費者）。

## 🔴 錯誤碼必須與 `paginate()` 完全一致

兩支的驗證邏輯是**刻意的重複**（見上：不能改 `paginate()`）。這組測試同時斷言兩支的
錯誤碼相同——日後有人只改其中一支的門檻或代碼，這裡會紅，而不是讓兩支列表 API 對同一個
非法輸入回不同的錯。
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
