"""et_quiz_description

Revision ID: 470b5293cc6a
Revises: e6a4c7b18d93
Create Date: 2026-08-25 17:47:00.000000

`ET_QUIZ` 新增 `DESCRIPTION`（TEXT，可空）——測驗說明，顯示於學員作答開始前。

## 為何現在才加

wireframe 之 `#quizModal` 一直畫著「測驗說明（顯示於開始前）」，但該欄位在
**data-model、#185 建表、spec_us3 三處皆不存在**。#203 規劃時盤出此不一致
（方向與 #202 之 `REQUIRE_APPROVAL` 相反——那次是 spec 有、wireframe 漏畫），
經 SA 裁示（#203 Q1）確認要有此欄位。

## 純文字，不是 HTML

與 `ET_MATERIAL.DESCRIPTION_HTML` 分屬兩條路徑，勿混用：

| | 來源 | 寫入時 | 渲染時 |
|---|---|---|---|
| `ET_MATERIAL.DESCRIPTION_HTML` | WYSIWYG 編輯器 | allow-list 消毒 | 受控 HTML |
| **`ET_QUIZ.DESCRIPTION`（本欄）** | 多行文字方塊 | **不消毒**（本就非 HTML）| **純文字**，不得 `dangerouslySetInnerHTML` |

可空：既有測驗無此資料，且說明本身為選填。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "470b5293cc6a"
down_revision: Union[str, None] = "e6a4c7b18d93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ET_QUIZ", sa.Column("DESCRIPTION", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ET_QUIZ", "DESCRIPTION")
