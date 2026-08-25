"""et_item_material_order_partial_unique

Revision ID: 4e911375d095
Revises: 470b5293cc6a
Create Date: 2026-08-25 17:47:30.000000

`ET_ITEM` / `ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC` 三處唯一約束改為**部分唯一索引**
（`WHERE DELETED = 0`）。

## 為何要改（#185 建表時的缺陷，與 #202 修 `ET_CHAPTER` 同一根因）

原約束未排除已軟刪除之列。真正的不變量是「**未刪除**之列間不重複」，寫成「所有列
（含已刪）不重複」則過嚴，且與本專案「一律軟刪除」的策略直接矛盾——刪除不會讓
該列讓出位置，等於刪了還佔著。

三張表各自的故障情境：

| 表 | 原約束 | 壞在哪 |
|---|---|---|
| `ET_ITEM` | `(CHAPTER_ID, SORT_ORDER)` | 刪除項目後「後續順序自動遞補」撞鍵——與 `ET_CHAPTER` 同一故障 |
| `ET_MATERIAL_VIDEO` | `(MATERIAL_ID, SORT_ORDER)` | 同上，刪影片後遞補失敗 |
| `ET_MATERIAL_DOC` | `(MATERIAL_ID, DOC_ID)` | **引用某文件 → 刪除 → 想再引用同一份，永久失敗**——已刪除的列仍佔著該組合 |

第三項與前兩項性質不同：它不是順序遞補問題，而是**已刪除的引用把該文件永久
擋在門外**。教師誤刪一份 DM 文件引用後將再也加不回來，且錯誤訊息會是
「同一教材不可重複引用同一文件」——指向一筆他看不見的資料，極難自行排除。

比照 DM 既有前例（`UX_DM_REVIEW_ONE_PENDING` 等 4 處）與 #202 之
`UX_ET_CHAPTER_COURSE_ORDER`，部分唯一索引以 `UX_` 前綴命名。

> 註：`ET_QUESTION` / `ET_OPTION` 之 `SORT_ORDER` 無唯一約束（僅一般索引），
> data-model 亦未要求其唯一，故不在本次調整範圍。

> 註：即使改為部分索引，**重排仍須兩階段寫入**（先移至負數暫存值再落定）——
> PostgreSQL 對非 deferrable 之唯一索引逐列即時檢核，而部分索引無法宣告
> deferrable。見 `app/et/course/repository.py::apply_order`（#202 已實作）。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "4e911375d095"
down_revision: Union[str, None] = "470b5293cc6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (表名, 舊唯一約束名, 新部分唯一索引名, 欄位)
_TARGETS = (
    ("ET_ITEM", "UQ_ET_ITEM_CHAPTER_ORDER", "UX_ET_ITEM_CHAPTER_ORDER", ["CHAPTER_ID", "SORT_ORDER"]),
    (
        "ET_MATERIAL_VIDEO",
        "UQ_ET_MATERIAL_VIDEO_ORDER",
        "UX_ET_MATERIAL_VIDEO_ORDER",
        ["MATERIAL_ID", "SORT_ORDER"],
    ),
    (
        "ET_MATERIAL_DOC",
        "UQ_ET_MATERIAL_DOC_MATERIAL_DOC",
        "UX_ET_MATERIAL_DOC_MATERIAL_DOC",
        ["MATERIAL_ID", "DOC_ID"],
    ),
)


def upgrade() -> None:
    for table, old_constraint, new_index, columns in _TARGETS:
        op.drop_constraint(old_constraint, table, type_="unique")
        op.create_index(
            new_index,
            table,
            columns,
            unique=True,
            postgresql_where=sa.text('"DELETED" = 0'),
        )


def downgrade() -> None:
    """還原為全表唯一約束。

    ⚠️ 若期間已產生「已刪除列與現存列共用同一組合」之資料（例如刪除項目後遞補順序、
    或重新引用曾刪除的 DM 文件），還原會因重複值而失敗——此為預期行為（原約束本就
    不容許該狀態），需先人工整理再降級。
    """
    for table, old_constraint, new_index, columns in reversed(_TARGETS):
        op.drop_index(new_index, table_name=table)
        op.create_unique_constraint(old_constraint, table, columns)
