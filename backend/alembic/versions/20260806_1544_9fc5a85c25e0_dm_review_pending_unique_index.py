"""dm_review_pending_unique_index

Revision ID: 9fc5a85c25e0
Revises: b7fa4b6e4fe7
Create Date: 2026-08-06 15:44:42.318267

「同一文件不可同時兩種送審」由 DB partial unique index 保證：同 DOC_ID 至多一筆 STATUS=PENDING。
應用層（review/service.submit）仍先 count 判斷給友善錯誤，此索引為並發後盾（杜絕雙送審 race）。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fc5a85c25e0"
down_revision: Union[str, None] = "b7fa4b6e4fe7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "UX_DM_REVIEW_ONE_PENDING",
        "DM_REVIEW",
        ["DOC_ID"],
        unique=True,
        postgresql_where=sa.text("\"STATUS\" = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("UX_DM_REVIEW_ONE_PENDING", table_name="DM_REVIEW")
