"""et_item_quiz_index

Revision ID: 1e57d1db82b2
Revises: 7d011f5f1cbc
Create Date: 2026-10-06 16:01:00

`ET_ITEM.QUIZ_ID` 補索引（#287，併入 #538 的 PR）。

`attempt/repository.quiz_context()` 的 `WHERE "QUIZ_ID" = ? AND "DELETED" = 0` 是學員端測驗
**授權鏈的第一跳**（測驗本體不帶 `COURSE_ID`，授權一定要經過 `ET_ITEM` → `ET_CHAPTER`），
每次進入測驗都會走到。PostgreSQL 不會為 FK 自動建立索引，原本是 `ET_ITEM` 的順序掃描。

刻意與 #538 的配對 migration（`7d011f5f1cbc`）分開：那支的 downgrade 有順序限制，
兩者分開可各自退版。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e57d1db82b2"
down_revision: Union[str, None] = "7d011f5f1cbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("IX_ET_ITEM_QUIZ", "ET_ITEM", ["QUIZ_ID"], unique=False)


def downgrade() -> None:
    op.drop_index("IX_ET_ITEM_QUIZ", table_name="ET_ITEM")
