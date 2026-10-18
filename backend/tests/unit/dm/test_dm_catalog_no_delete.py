"""DM 受控清單四張表不得帶 `DELETED` 欄位（#508）。

`DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG` 的政策是**永不刪除**——
淘汰改停用（`IS_ENABLED`）、停用後既有引用保留。`catalog/models.py` 的檔案
docstring 從一開始就這麼寫，但四個 model 卻繼承了帶 `DELETED` 的 `BaseModel`。

## 為什麼要用測試釘住，而不是改完 base 就算了

一個**永遠是 0** 的欄位，會讓每個讀這四張表的人都得自己決定要不要濾——
濾不濾都沒差，**直到哪天有差**。#508 之前實況已經不一致：`catalog/adapter.py`
全檔只有 `list_controlled_kinds` 一處濾 `DELETED = 0`，`list_controlled` 與
`list_audiences` 都沒濾。

⛔ **修法是消除欄位，不是補上缺的過濾。** `sti-coding-style` 明寫「加 default /
fallback 前先列出現在哪個 code path 會走到；找不到實際 caller → 不加」——
為一條**不存在的刪除路徑**補八處過濾正好違反這條。換 base 的方向相反：
沒有欄位 → 不濾是正確的 → 標籤組不可能被軟刪除 → 連帶缺陷結構上消失。

> 連帶缺陷指：`dp/params/service.py` 的 `_split_sections` 以 `tag_group_code`
> 配對，而 `list_controlled_kinds` 濾 `deleted == 0`、`list_controlled` 不濾。
> 若某標籤組被軟刪除，其下標籤會**從 DP03 靜默消失**（仍掛在文件上、但無法維護）。

⚠️ `DM_DOC_TAG` 是**不同的表**，有真正的軟刪除復用機制（移除＝`deleted=1` 不刪列，
重新加回時復用該列），不在本檔範圍內——最後一條反向探針專門守住這點。
"""

import pytest

from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.document.models import DmDocTag

pytestmark = pytest.mark.unit

#: 政策為「永不刪除、淘汰改停用」的四張受控表。
_CONTROLLED = (DmCategory, DmFunc, DmTagGroup, DmTag)


def _column_names(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def test_受控四表不得帶_deleted_欄位() -> None:
    """四張表皆須繼承 `BaseModelNoDelete`（或等效之無 DELETED 基底）。"""
    for model in _CONTROLLED:
        assert "DELETED" not in _column_names(model), (
            f"{model.__name__}（{model.__tablename__}）不應有 DELETED 欄位："
            "本表政策為永不刪除、淘汰改停用，帶著永遠為 0 的欄位只會讓讀取端各自決定要不要濾"
        )


def test_受控四表仍保有可更新之標準欄位() -> None:
    """只砍 `DELETED`，`CREATED_*` / `UPDATED_*` 不得一起消失。

    這四張表**可改名、可停用**，故需要 `UPDATED_*`——若誤用 `AuditLogBaseModel`
    （append-only、僅 `CREATED_*`）或其他基底，本條會紅。
    """
    for model in _CONTROLLED:
        cols = _column_names(model)
        for col in ("CREATED_USER", "CREATED_DATE", "UPDATED_USER", "UPDATED_DATE"):
            assert col in cols, f"{model.__name__}（{model.__tablename__}）應保有 {col}"


def test_反向探針_dm_doc_tag_仍保有_deleted() -> None:
    """⚠️ `DM_DOC_TAG` 有**真正的**軟刪除，不得被本次改動波及。

    它的移除語意是 `deleted=1` 不刪列、重新加回時復用該列（見 `dm/catalog/service.py`
    「兩個計數皆須濾 `DELETED = 0`」一段）。若本條變紅，代表砍欄位時砍過頭了。
    """
    assert "DELETED" in _column_names(DmDocTag), (
        "DM_DOC_TAG 必須保留 DELETED：它採軟刪除復用，與受控四表的「永不刪除」是不同語意"
    )
