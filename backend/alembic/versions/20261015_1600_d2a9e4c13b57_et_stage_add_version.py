"""et_stage_add_version

Revision ID: d2a9e4c13b57
Revises: 0d17180b7546
Create Date: 2026-10-15 16:00:00.000000

暫存列加上樂觀鎖欄位（#631 PR 2/4）。

異動說明：
- `ET_COURSE_CONTENT_STAGE` 新增 `VERSION`（INTEGER NOT NULL DEFAULT 0）

## 為何暫存也要樂觀鎖

既有的編輯端以**每個實體的 `VERSION`** 做並行保護（`FR-ET-US3-15`「不同實體並行編輯
互不衝突」）：`rename_chapter` 等方法把前端帶回的 `version` 寫進 `WHERE`，命中 0 列就回
`ET_LOCK_001` 要使用者重新載入。

已發布課程的編輯改走暫存區之後，前端讀的是暫存樹——若暫存列沒有 `VERSION`，同一位教師
兩個分頁同時編輯同一個章節會**後寫的贏且無任何提示**。那等於「課程一旦發布，教師就失去
了並行編輯的保護」，而那不是任何人裁示過的行為改變。

🔴 本欄位**與活表列的 `VERSION` 是兩回事**（但初值承接自活表，見下）：

| | 保護什麼 |
|---|---|
| `ET_CHAPTER.VERSION` 等 | 活表列的並行寫入（草稿課程的編輯、以及「更新」套用時）|
| `ET_COURSE_CONTENT_STAGE.VERSION` | **暫存列**的並行寫入（已發布課程的編輯期間）|

⛔ `stage_entities._NEVER_STAGED` 仍然排除 `version`——**不得搬進 `PAYLOAD`**
（`test_不搬_pk_排序_樂觀鎖與稽核欄位` 釘住這件事）。那與本欄位是兩回事：payload 是
「內容」，本欄位是暫存列自己的併發控制。

⚠️ **初值承接自活表那一列**：教師開編輯頁時第一次編輯之前還沒有暫存列，前端拿到的
`VERSION` 來自活表；初值若設 0，第一次編輯必然 409 而教師根本沒有並行對象。承接的只是
初值——此後暫存列自己遞增、活表那一列不動，兩者隨即分岔。

## 為何不是「編輯期間也鎖課程」

那會讓第二個分頁直接被擋（而不是提示衝突），且教師長時間開著編輯頁會一直持有鎖。
PR 1 的 `lock_course` 只在「更新」那一瞬間取，刻意不涵蓋編輯期間。

## 既有資料

執行當下 `ET_COURSE_CONTENT_STAGE` 為空（PR 1 的編輯端尚未導向暫存區），`server_default`
僅供欄位宣告完整，不需回填。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "d2a9e4c13b57"
down_revision: str | None = "c3fcddaa575b"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "ET_COURSE_CONTENT_STAGE"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("VERSION", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "VERSION")
