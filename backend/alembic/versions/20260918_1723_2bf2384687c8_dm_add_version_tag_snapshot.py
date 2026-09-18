"""dm_add_version_tag_snapshot

Revision ID: 2bf2384687c8
Revises: 6e65f03ce681
Create Date: 2026-09-18 17:23:32.801312

新增版本標籤快照表，標籤改為核准發布時生效。

異動說明：
- 影響 Table：新增 DM_VERSION_TAG；讀 DM_DOC_TAG 回填在途版本（不修改 DM_DOC_TAG）
- 標籤原為文件層、存檔當下即生效（spec_us5 FR-003）；#377 改為草稿階段存版本層，
  核准發布時才套用至文件層 DM_DOC_TAG（生效值），退回 / 撤回不套用
- 回填範圍限 STATUS IN ('DRAFT','PENDING_REVIEW') 之有效版本：在途草稿送簽時改檢核版本層
  可見對象，未回填會被 DM_DOC_005 誤擋。已發布 / 已退回版本不回填——前者標籤已在文件層
  生效，後者續編時由應用層以文件層現值預帶
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "2bf2384687c8"
down_revision: Union[str, None] = "6e65f03ce681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 回填：以所屬文件當下之有效標籤作為在途版本之快照——撰寫者編輯當時看到的即此值。
# ON CONFLICT 僅為重跑保險：來源已篩 DELETED=0，(VERSION_ID, TAG_ID) 於單次語句內天然唯一。
_BACKFILL_INFLIGHT = text(
    'INSERT INTO "DM_VERSION_TAG" ("VERSION_ID", "TAG_ID", "CREATED_USER", "CREATED_DATE", "DELETED") '
    'SELECT v."VERSION_ID", t."TAG_ID", :u, :now, 0 '
    'FROM "DM_DOC_VERSION" v '
    'JOIN "DM_DOC_TAG" t ON t."DOC_ID" = v."DOC_ID" AND t."DELETED" = 0 '
    'WHERE v."DELETED" = 0 AND v."STATUS" IN (\'DRAFT\', \'PENDING_REVIEW\') '
    'ON CONFLICT ("VERSION_ID", "TAG_ID") DO NOTHING'
)


def upgrade() -> None:
    op.create_table(
        "DM_VERSION_TAG",
        sa.Column("VERSION_TAG_ID", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("VERSION_ID", sa.BigInteger(), nullable=False),
        sa.Column("TAG_ID", sa.BigInteger(), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("DELETED", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["VERSION_ID"], ["DM_DOC_VERSION.VERSION_ID"], name="FK_DM_VERSION_TAG_VERSION"),
        sa.ForeignKeyConstraint(["TAG_ID"], ["DM_TAG.TAG_ID"], name="FK_DM_VERSION_TAG_TAG"),
        sa.PrimaryKeyConstraint("VERSION_TAG_ID", name="PK_DM_VERSION_TAG"),
        sa.UniqueConstraint("VERSION_ID", "TAG_ID", name="UQ_DM_VERSION_TAG_VERSION_TAG"),
    )
    op.create_index("IX_DM_VERSION_TAG_VERSION", "DM_VERSION_TAG", ["VERSION_ID"], unique=False)
    op.create_index("IX_DM_VERSION_TAG_TAG", "DM_VERSION_TAG", ["TAG_ID"], unique=False)
    op.execute(_BACKFILL_INFLIGHT.bindparams(u="SYSTEM", now=datetime.now(timezone.utc)))


def downgrade() -> None:
    op.drop_index("IX_DM_VERSION_TAG_TAG", table_name="DM_VERSION_TAG")
    op.drop_index("IX_DM_VERSION_TAG_VERSION", table_name="DM_VERSION_TAG")
    op.drop_table("DM_VERSION_TAG")
