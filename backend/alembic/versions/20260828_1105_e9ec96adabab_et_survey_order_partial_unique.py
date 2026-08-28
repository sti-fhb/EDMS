"""et_survey_order_partial_unique

Revision ID: e9ec96adabab
Revises: dfa09c18c56e
Create Date: 2026-08-28 11:05:28.141297

`ET_SURVEY_QUESTION` / `ET_SURVEY_OPTION` 之順序唯一約束改為**部分唯一索引**
（`WHERE DELETED = 0`）。

## 為何要改（#185 建表時的缺陷，第四次遇到）

原約束未排除已軟刪除之列。真正的不變量是「**未刪除**之列間順序不重複」，寫成
「所有列（含已刪）不重複」則過嚴，與本專案「一律軟刪除」的策略直接矛盾——刪除
不會讓該列讓出位置，等於刪了還佔著。

前三次分別由 #202（`ET_CHAPTER`）與 #203（`ET_ITEM` / `ET_MATERIAL_VIDEO` /
`ET_MATERIAL_DOC`）修掉。

| 表 | 原約束 | 壞在哪 |
|---|---|---|
| `ET_SURVEY_QUESTION` | `(SURVEY_ID, SORT_ORDER)` | 刪題後剩餘題目順序遞補撞鍵 |
| `ET_SURVEY_OPTION` | `(SQ_ID, SORT_ORDER)` | 選項全量覆寫時，舊列軟刪後新列自 1 起編號會撞上舊列 |

第二項是本次一定會踩到的——更新題目採「舊選項軟刪 + 新選項自 1 起插入」（比照
`EtQuizRepository.replace_question`），若舊列仍佔著 `SORT_ORDER=1`，第一個新選項
就插不進去。

## `UQ_ET_SURVEY_COURSE` 為何不在本次範圍

`ET_SURVEY` 之 `(COURSE_ID)` 唯一約束同樣未排除軟刪除列，但 **SA 裁示（#204 Q1 → B）
問卷不可刪除、只能停用**——沒有刪除就不會產生軟刪列，該約束不會壞。

⚠️ 這是「用不到所以沒壞」，不是「修好了」。日後若開放問卷刪除，此約束會立刻變成
缺陷，且症狀極難解讀：錯誤訊息會是「一門課程僅可建立 1 份課後問卷」，卻指向一筆
使用者看不見的資料。`app/et/survey/models.py` 該約束上方已留註解記明此前提。

> 註：即使改為部分索引，**重排仍須兩階段寫入**（先移至負數暫存值再落定）——
> PostgreSQL 對非 deferrable 之唯一索引逐列即時檢核，而部分索引無法宣告
> deferrable。見 `app/et/course/repository.py::apply_order`（#202 已實作）。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9ec96adabab"
down_revision: Union[str, None] = "dfa09c18c56e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (表名, 舊唯一約束名, 新部分唯一索引名, 欄位)
_TARGETS = (
    (
        "ET_SURVEY_QUESTION",
        "UQ_ET_SURVEY_QUESTION_ORDER",
        "UX_ET_SURVEY_QUESTION_ORDER",
        ["SURVEY_ID", "SORT_ORDER"],
    ),
    (
        "ET_SURVEY_OPTION",
        "UQ_ET_SURVEY_OPTION_ORDER",
        "UX_ET_SURVEY_OPTION_ORDER",
        ["SQ_ID", "SORT_ORDER"],
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

    ⚠️ 若期間已產生「已刪除列與現存列共用同一組合」之資料（刪題後遞補順序、或更新
    題目時換過一批選項），還原會因重複值而失敗——此為預期行為（原約束本就不容許該
    狀態），需先人工整理再降級。
    """
    for table, old_constraint, new_index, columns in reversed(_TARGETS):
        op.drop_index(new_index, table_name=table)
        op.create_unique_constraint(old_constraint, table, columns)
