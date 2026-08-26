"""dm_one_draft_index_exclude_deleted

Revision ID: 8afb64daa14b
Revises: 6a96fd1016fd
Create Date: 2026-08-25 14:29:52.671527

「每人每文件一份草稿」partial unique index（`UX_DM_DOC_VERSION_ONE_DRAFT`）原條件僅
`STATUS='DRAFT'`，未排除軟刪列——US9 個人專區引入草稿刪除（`DELETED=1` 但 STATUS 仍為 DRAFT）後，
被軟刪之草稿仍佔唯一槽，導致同文件同人再開新草稿時撞索引（誤報「已有草稿」DM_DOC_009）。
本 migration 重建索引為 `STATUS='DRAFT' AND DELETED=0`，讓軟刪草稿釋出唯一槽。

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8afb64daa14b"
down_revision: Union[str, None] = "6a96fd1016fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "UX_DM_DOC_VERSION_ONE_DRAFT"
_TABLE = "DM_DOC_VERSION"
_COLS = ["DOC_ID", "CREATED_USER"]


def upgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(
        _INDEX,
        _TABLE,
        _COLS,
        unique=True,
        postgresql_where=sa.text('"STATUS" = \'DRAFT\' AND "DELETED" = 0'),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(
        _INDEX,
        _TABLE,
        _COLS,
        unique=True,
        postgresql_where=sa.text("\"STATUS\" = 'DRAFT'"),
    )
