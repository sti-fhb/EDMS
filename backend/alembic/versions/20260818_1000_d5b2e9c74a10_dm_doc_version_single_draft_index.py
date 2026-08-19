"""dm_doc_version_single_draft_index

Revision ID: d5b2e9c74a10
Revises: c4a1f8b2d3e5
Create Date: 2026-08-18 10:00:00.000000

「每人每文件一份草稿」不變式（US5）由 DB partial unique index 保證：同 (DOC_ID, CREATED_USER)
至多一筆 STATUS='DRAFT'。不同撰寫者可各自對同一文件開草稿、互不阻擋（避免留草稿/請假卡住全部人）。
應用層（editor/service.add_version）仍先查 get_open_draft_version 給友善錯誤（DM_DOC_009），
此索引為並發後盾。真正互斥（同文件至多一筆進行中送審）由 UX_DM_REVIEW_ONE_PENDING 負責。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5b2e9c74a10"
down_revision: Union[str, None] = "c4a1f8b2d3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "UX_DM_DOC_VERSION_ONE_DRAFT",
        "DM_DOC_VERSION",
        ["DOC_ID", "CREATED_USER"],
        unique=True,
        postgresql_where=sa.text("\"STATUS\" = 'DRAFT'"),
    )


def downgrade() -> None:
    op.drop_index("UX_DM_DOC_VERSION_ONE_DRAFT", table_name="DM_DOC_VERSION")
