"""dm_catalog_drop_deleted

Revision ID: c3fcddaa575b
Revises: 7c4e19ab3f52
Create Date: 2026-10-18 23:23:44.227717

DM 受控清單四張表移除 `DELETED` 欄位（#508）。

`DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG` 的政策是**永不刪除**——淘汰改停用
（`IS_ENABLED`）、停用後既有引用保留。`catalog/models.py` 的檔案 docstring 從一開始就這麼
寫，但四個 model 繼承了帶 `DELETED` 的 `BaseModel`，於是帶著一個全後端**沒有任何寫入路徑、
永遠是 0** 的欄位。

異動說明：
- 影響 Table：`DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG`，各砍一個 `DELETED` 欄位
- 不動資料；四張表的該欄位一律為 0，砍掉不影響任何既有列的語意
- 同批改 model 繼承 `BaseModelNoDelete`、移除 `catalog/adapter.py` 中唯一一處過濾

## 為什麼修法是砍欄位，而不是補齊缺少的過濾

一個永遠是 0 的欄位，會讓每個讀取端各自決定要不要濾——濾不濾都沒差，**直到哪天有差**。
本次之前實況已經不一致：`adapter.py` 全檔只有 `list_controlled_kinds` 一處濾 `DELETED = 0`，
`list_controlled` 與 `list_audiences` 都沒濾。

`sti-coding-style` 明寫「加 default / fallback 前先列出現在哪個 code path 會走到；找不到實際
caller → 不加」。為一條**不存在的刪除路徑**補八處過濾正好違反這條；砍欄位的方向相反——
沒有欄位 → 不濾是正確的 → 標籤組不可能被軟刪除。

連帶消除的潛在缺陷：`dp/params/service.py` 的 `_split_sections` 以 `tag_group_code` 配對，
而當時 `list_controlled_kinds` 濾、`list_controlled` 不濾。若某標籤組被軟刪除，其下標籤會
**從 DP03 靜默消失**（仍掛在文件上、但無法維護）。欄位消失後此情境結構上不存在。

⚠️ **`DM_DOC_TAG` 不在本次範圍**——它是不同的表，有真正的軟刪除復用機制（移除＝`deleted=1`
不刪列，重新加回時復用該列），繼承 `BaseModel` 是對的。

## 降版為何要先給 server_default 再拿掉

原建表（`20260806_1031_2d877f07412e`）是 `sa.Column("DELETED", sa.Integer(), nullable=False)`
——**沒有** server_default，預設值由 ORM 層 `default=0` 提供。

降版時若照原樣直接 `add_column(nullable=False)`，PostgreSQL 會因既有資料列無值可填而拒絕。
故先帶 `server_default="0"` 補齊現有列，再 `alter_column` 移除 server_default，結果與原建表
之 schema 完全一致。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3fcddaa575b"
down_revision: Union[str, None] = "7c4e19ab3f52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 政策為「永不刪除、淘汰改停用」的四張受控表。⛔ 不含 DM_DOC_TAG（真軟刪除）。
_TABLES = ("DM_CATEGORY", "DM_FUNC", "DM_TAG_GROUP", "DM_TAG")


def upgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "DELETED")


def downgrade() -> None:
    for table in _TABLES:
        # server_default 僅用於補齊既有列，補完即移除——見本檔 docstring 末段。
        op.add_column(table, sa.Column("DELETED", sa.Integer(), nullable=False, server_default="0"))
        op.alter_column(table, "DELETED", server_default=None)
