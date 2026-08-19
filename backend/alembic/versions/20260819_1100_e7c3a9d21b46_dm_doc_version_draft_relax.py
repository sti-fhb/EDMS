"""dm_doc_version_draft_relax

Revision ID: e7c3a9d21b46
Revises: d5b2e9c74a10
Create Date: 2026-08-19 11:00:00.000000

US5「存草稿不卡必填」+「版號只卡與已發布重複」：
- 版本號唯一由「全域（含草稿）」改為「只對已發布」：drop UQ_DM_DOC_VERSION_DOC_NO（全域唯一約束），
  改建 partial unique index UX_DM_DOC_VERSION_RELEASED_NO WHERE STATUS IN ('PUBLISHED','SUPERSEDED')。
  草稿 / 送審中 / 退回可自由重複或留空版號；送簽時應用層才檢核不與已發布重複。
- FILE_* 改可空：草稿可暫無檔案（填一半先存），送簽 / 發布時才必備。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c3a9d21b46"
down_revision: Union[str, None] = "d5b2e9c74a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FILE_COLS = ("FILE_NAME", "FILE_PATH", "FILE_SIZE", "FILE_MIME")


def upgrade() -> None:
    op.drop_constraint("UQ_DM_DOC_VERSION_DOC_NO", "DM_DOC_VERSION", type_="unique")
    op.create_index(
        "UX_DM_DOC_VERSION_RELEASED_NO",
        "DM_DOC_VERSION",
        ["DOC_ID", "VERSION_NO"],
        unique=True,
        postgresql_where=sa.text("\"STATUS\" IN ('PUBLISHED', 'SUPERSEDED')"),
    )
    for col in _FILE_COLS:
        op.alter_column("DM_DOC_VERSION", col, nullable=True)


def downgrade() -> None:
    for col in _FILE_COLS:
        op.alter_column("DM_DOC_VERSION", col, nullable=False)
    op.drop_index("UX_DM_DOC_VERSION_RELEASED_NO", table_name="DM_DOC_VERSION")
    op.create_unique_constraint("UQ_DM_DOC_VERSION_DOC_NO", "DM_DOC_VERSION", ["DOC_ID", "VERSION_NO"])