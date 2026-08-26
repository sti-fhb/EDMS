"""et_chapter_order_partial_unique

Revision ID: e6a4c7b18d93
Revises: d5f9a2b8e614
Create Date: 2026-08-24 11:30:00.000000

`ET_CHAPTER` 之 `(COURSE_ID, SORT_ORDER)` 唯一約束改為**部分唯一索引**
（`WHERE DELETED = 0`）。

## 為何要改（#185 建表時的缺陷）

原 `UQ_ET_CHAPTER_COURSE_ORDER` 未排除已軟刪除之列，造成兩個實際故障：

1. **刪除後無法遞補順序**——刪掉第 1 章後，其列雖為 `DELETED=1` 卻仍佔住
   `(course, 1)`；把第 2 章遞補為 1 時撞唯一鍵。data-model §ET_CHAPTER 明訂
   「後續章節順序自動遞補」，原約束使該規則無法實作。
2. **拖拉重排時中途衝突**——交換相鄰兩章需短暫出現重複值。

真正的不變量是「**未刪除**之章節間順序不重複」，原約束把它寫成「所有列（含已刪）
不重複」，過嚴且與軟刪除策略矛盾。改為部分索引即精確表達該不變量。

比照 DM 既有前例（`UX_DM_REVIEW_ONE_PENDING`、`UX_DM_DOC_VERSION_SINGLE_DRAFT` 等
4 處），部分唯一索引以 `UX_` 前綴命名。

> 註：即使改為部分索引，**重排仍須兩階段寫入**（先移至負數暫存值再落定）——
> PostgreSQL 對非 deferrable 之唯一索引逐列即時檢核，而部分索引無法宣告 deferrable。
> 見 `app/et/course/repository.py::apply_order`。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e6a4c7b18d93"
down_revision: Union[str, None] = "d5f9a2b8e614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ET_CHAPTER"
_OLD_CONSTRAINT = "UQ_ET_CHAPTER_COURSE_ORDER"
_NEW_INDEX = "UX_ET_CHAPTER_COURSE_ORDER"


def upgrade() -> None:
    op.drop_constraint(_OLD_CONSTRAINT, _TABLE, type_="unique")
    op.create_index(
        _NEW_INDEX,
        _TABLE,
        ["COURSE_ID", "SORT_ORDER"],
        unique=True,
        postgresql_where=sa.text('"DELETED" = 0'),
    )


def downgrade() -> None:
    """還原為全表唯一約束。

    ⚠️ 若期間已存在「已刪除章節與現存章節共用同一 `SORT_ORDER`」之資料，
    還原會因重複值而失敗——此為預期行為（原約束本就不容許該狀態），
    需先人工整理再降級。
    """
    op.drop_index(_NEW_INDEX, table_name=_TABLE)
    op.create_unique_constraint(_OLD_CONSTRAINT, _TABLE, ["COURSE_ID", "SORT_ORDER"])
