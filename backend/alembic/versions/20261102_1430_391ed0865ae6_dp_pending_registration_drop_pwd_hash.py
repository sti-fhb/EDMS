"""dp_pending_registration_drop_pwd_hash

Revision ID: 391ed0865ae6
Revises: 7ade05c26fd8
Create Date: 2026-11-02 14:30:00.000000

移除 DP_PENDING_REGISTRATION 未使用的 PWD_HASH 欄位（#668）。

異動說明：
- 影響 Table：DP_PENDING_REGISTRATION（DROP COLUMN "PWD_HASH"）
- ⚠️ 只動本表。DP_USER.PWD_HASH、DP_PWD_HIST.PWD_HASH 為使用中欄位，不在本 migration 範圍

## 為什麼可以直接 DROP

#212 起本表所有寫入路徑（自助註冊、管理者邀請、重寄邀請、重寄驗證信）皆寫入 NULL，
啟用 / 驗證流程的密碼一律於該步當場雜湊、不讀本欄位 ⇒ 既有列此欄恆為 NULL，DROP 不遺失資料。
本表為暫存表（TTL 30 分鐘 + SCHDP001 清理），資料量小，DROP COLUMN 僅改 catalog、無重寫成本。

## downgrade

加回 VARCHAR(100) NULL 欄位（與移除前定義一致）。既有列回填為 NULL，與移除前的實際內容相同。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "391ed0865ae6"
down_revision: Union[str, None] = "7ade05c26fd8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("DP_PENDING_REGISTRATION", "PWD_HASH")


def downgrade() -> None:
    op.add_column("DP_PENDING_REGISTRATION", sa.Column("PWD_HASH", sa.String(100), nullable=True))
