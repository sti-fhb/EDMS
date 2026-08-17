"""dp_drop_res_id_rename_invite_id

Revision ID: c4a1f8b2d3e5
Revises: 9fc5a85c25e0
Create Date: 2026-08-13 10:30:00.000000

移除孤兒欄位 RES_ID；邀請識別碼正名為 INVITE_ID（#158）。

異動說明：
- RES_ID 源自 TBMS 之「來源功能 ID」（FK → DP_MENU），但 EDMS 不設 DP_MENU
  （無全域 RBAC / 功能選單），來源功能改記於 DP_AUDIT_LOG.FUNC_NAME，
  該欄位在 EDMS 已無存在依據。
- DP_PENDING_REGISTRATION：RES_ID → INVITE_ID（**RENAME 保值**，非 DROP+ADD）。
  該欄實際語意為「邀請之對外識別碼」（供重寄 / 取消端點指認單筆邀請），與
  「來源功能 ID」相反（前者每列唯一、後者同功能共用），故正名。
- 其餘 6 表（DP_USER / DP_PARAM_M / DP_PARAM_D / DP_NOTIFY_TEMPLATE /
  DP_SCHEDULE / DP_PWD_RESET）：DROP COLUMN RES_ID。
  已實測確認此 6 表之 RES_ID 全為 NULL（無任何 create 路徑寫入），故不遺失資料。
- DM 各業務表原採 BaseModelNoResId、本無此欄位，不受影響。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a1f8b2d3e5"
down_revision: Union[str, None] = "9fc5a85c25e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# RES_ID 全為 NULL、直接移除之表
_DROP_TABLES = (
    "DP_USER",
    "DP_PARAM_M",
    "DP_PARAM_D",
    "DP_NOTIFY_TEMPLATE",
    "DP_SCHEDULE",
    "DP_PWD_RESET",
)


def upgrade() -> None:
    # 更名保值：autogenerate 會誤判為 DROP+ADD（資料遺失），故明確用 alter_column
    op.alter_column("DP_PENDING_REGISTRATION", "RES_ID", new_column_name="INVITE_ID")

    for table in _DROP_TABLES:
        op.drop_column(table, "RES_ID")


def downgrade() -> None:
    for table in _DROP_TABLES:
        op.add_column(table, sa.Column("RES_ID", sa.String(length=30), nullable=True))

    op.alter_column("DP_PENDING_REGISTRATION", "INVITE_ID", new_column_name="RES_ID")