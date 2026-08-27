"""dm_doc_version_add_assigned_reviewer

Revision ID: f29cb69d6199
Revises: 6eea417bdf8a
Create Date: 2026-08-27 11:42:45.934897

為 DM_DOC_VERSION 增設可空 ASSIGNED_REVIEWER 欄：草稿階段記住的「指定審核者」，供續編時預帶
（#222 Round-2；送簽仍以表單值建 DM_REVIEW，此欄僅為存草稿之便利記憶）。可空、無需回填。

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f29cb69d6199"
down_revision: Union[str, None] = "6eea417bdf8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("DM_DOC_VERSION", sa.Column("ASSIGNED_REVIEWER", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("DM_DOC_VERSION", "ASSIGNED_REVIEWER")
