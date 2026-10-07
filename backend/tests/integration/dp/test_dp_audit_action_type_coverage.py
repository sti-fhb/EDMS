"""`ACTION_TYPE` 三處定義的一致性護欄（#548）。

## 為何需要這條

新增一個稽核操作類別要同時改三處，`dp/audit/router.py` 的註解列了這張清單——而那張
清單是**事後補的**：`EXPORT` 於 #322 導入時只補了 label，漏了 `_Action` 值域與
`DP_PARAM.ACTION_TYPE` 種子，直到 #477 才被發現。症狀是「操作類別」下拉選得到「匯出」、
查詢卻被擋成 422。

**漏掉的後果是靜默的**：寫入端照樣寫得進去（`ACTION_TYPE` 是 `String(10)`、無 CHECK
constraint），只有查詢與下拉會壞，而那兩件事沒有任何既有測試會因此變紅。

本檔把那張清單變成可執行的斷言。⛔ 新增值時請補齊三處，不要改這裡的斷言來讓它變綠。
"""

import pytest
from sqlalchemy import select

from app.dp.audit.query_service import _ACTION_LABELS
from app.dp.audit.router import _Action
from app.dp.params.models import DpParamDetail

pytestmark = pytest.mark.integration

_PARAM_ID = "ACTION_TYPE"


def _literal_values() -> set[str]:
    """取 `Literal[...]` 的字面值集合。"""
    return set(_Action.__args__)


async def _seeded_keys(db) -> set[str]:
    rows = await db.scalars(
        select(DpParamDetail.param_key).where(
            DpParamDetail.param_id == _PARAM_ID,
            DpParamDetail.deleted == 0,
        )
    )
    return set(rows)


async def test_三處定義完全一致(db) -> None:
    """label 表、router 值域、種子清單三者的鍵必須相同。

    ⚠️ 以**集合相等**而非「包含」斷言：任一方向的落差都是缺陷。
    多了（label 有、種子沒有）→ 下拉選得到卻篩不出東西；
    少了（種子有、值域沒有）→ 該值寫得進 DB 但查詢回 422。
    """
    labels = set(_ACTION_LABELS)
    seeded = await _seeded_keys(db)

    assert labels == _literal_values(), "_ACTION_LABELS 與 router._Action 不一致"
    assert labels == seeded, f"_ACTION_LABELS 與 DP_PARAM.ACTION_TYPE 種子不一致：{labels ^ seeded}"


async def test_母體非空(db) -> None:
    """🔴 錨點：三個空集合也會「完全一致」。

    種子沒跑、或 `_ACTION_LABELS` 被整個清空時，上一條會靜默通過——這正是
    `not in` / 集合比較類斷言最常見的假陽性。
    """
    assert len(await _seeded_keys(db)) >= 7, "至少 7 個值（LOGIN/LOGOUT/CREATE/UPDATE/DELETE/EXPORT/QUERY）"


async def test_query_類別已就緒(db) -> None:
    """#548 新增的值在三處都在——與上面的一致性斷言互補。

    ⚠️ 一致性那條在「三處都漏了 QUERY」時仍會通過（三邊一致地缺），本條釘住它確實存在。
    """
    assert "QUERY" in _ACTION_LABELS
    assert "QUERY" in _literal_values()
    assert "QUERY" in await _seeded_keys(db)
