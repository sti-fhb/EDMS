"""et_retry_reset_kind

Revision ID: b8e2d4f61a37
Revises: 3f7b9adcc1ee
Create Date: 2026-10-18 15:00:00.000000

`ET_QUIZ_RETRY_RESET` 新增 `RESET_KIND`（#709）。

## 為何要分種類

「要求重測」（#361，測驗內容已改）與「重置重考次數」（ET02，同一份測驗多給機會）原本
寫入同一張表、只記起點。兩者對學員的意義不同：

| 種類 | 分段顯示 | 最高分／平均成績 |
|---|---|---|
| `RETEST` | 「教師要求重測（測驗內容已更新）」| 只計最近一次 `RETEST` 之後 |
| `RETRY` | 「重考次數已重置」| 所有輪次（不變）|

## 🔴 舊列不回填，一律 `NULL`

#361 的批次寫入雖可由「同一 `EXECUTED_AT`、同一測驗多人」推測，但**不可靠**（教師對
單一學員連續重置也會同一時刻）。猜錯的代價是改動學員的結業成績，故不猜：`NULL`
＝原因未知，分段顯示中性文字、成績口徑比照 `RETRY`（即維持現狀）。

可為空（`nullable=True`）且無 server default——append-only 表，舊列本來就不會再被寫。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b8e2d4f61a37"
down_revision: Union[str, None] = "3f7b9adcc1ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ET_QUIZ_RETRY_RESET"
_CK = "CK_ET_QUIZ_RETRY_RESET_KIND"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("RESET_KIND", sa.String(10), nullable=True))
    op.create_check_constraint(_CK, _TABLE, "\"RESET_KIND\" IS NULL OR \"RESET_KIND\" IN ('RETEST', 'RETRY')")


def downgrade() -> None:
    op.drop_constraint(_CK, _TABLE, type_="check")
    op.drop_column(_TABLE, "RESET_KIND")
