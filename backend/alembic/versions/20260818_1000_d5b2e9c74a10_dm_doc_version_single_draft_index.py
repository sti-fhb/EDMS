"""dm_doc_version_single_draft_index

Revision ID: d5b2e9c74a10
Revises: c4a1f8b2d3e5
Create Date: 2026-08-18 10:00:00.000000

「單一草稿」不變式（US5 Q1=A：同一文件至多一個未送簽草稿版本）由 DB partial unique index 保證：
同 DOC_ID 至多一筆 STATUS='DRAFT'。應用層（editor/service.add_version）仍先查 get_open_draft_version
給友善錯誤（DM_DOC_009），此索引為並發後盾（杜絕兩個並發 add_version 同時建草稿之 race）。
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
        ["DOC_ID"],
        unique=True,
        postgresql_where=sa.text("\"STATUS\" = 'DRAFT'"),
    )


def downgrade() -> None:
    op.drop_index("UX_DM_DOC_VERSION_ONE_DRAFT", table_name="DM_DOC_VERSION")
