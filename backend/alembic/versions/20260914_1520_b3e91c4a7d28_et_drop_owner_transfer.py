"""ET: 移除 ET_OWNER_TRANSFER（擁有者轉讓功能取消）

2026-09-14 裁示：課程擁有者**不由任何人在系統內轉讓**——教師不行、管理者也不行。
`ET_COURSE.OWNER_ID` 於建立當下記錄後即為終局，「永久不可變更」自此在應用層字面成立。

極少數必須強制接手的情況（教師離職且課程需有人接管）改由直接修改資料庫處理。已知代價：
那條路徑**不留任何應用層紀錄**，原本 `spec.md` §擁有權判定要求的 `DP_AUDIT_LOG`
（`FUNC_NAME=ET-OWNER`）與本表兩份紀錄都不會有。裁示時已評估該情境罕見、值得用這個
代價換掉一條破例路徑。

本表自 `9aa92b82d0a0`（ET 建表）起存在，但**從未有任何程式碼寫入過**——轉讓功能在
#303 開發期間實作、於同一個 issue 內依裁示移除，未曾合併上線。故 `upgrade` 不需要
搬移資料，`downgrade` 重建空表即可。

Revision ID: b3e91c4a7d28
Revises: cb17257ddf60
Create Date: 2026-09-14 15:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b3e91c4a7d28"
down_revision: Union[str, None] = "cb17257ddf60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("IX_ET_OWNER_TRANSFER_COURSE", table_name="ET_OWNER_TRANSFER")
    op.drop_table("ET_OWNER_TRANSFER")


def downgrade() -> None:
    """重建空表——欄位定義逐字取自 `9aa92b82d0a0`，不是重新設計。"""
    op.create_table(
        "ET_OWNER_TRANSFER",
        sa.Column("TRANSFER_ID", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("COURSE_ID", sa.BigInteger(), nullable=False),
        sa.Column("FROM_OWNER_ID", sa.String(length=20), nullable=False),
        sa.Column("TO_OWNER_ID", sa.String(length=20), nullable=False),
        sa.Column("REASON", sa.Text(), nullable=False),
        sa.Column("EXECUTED_BY", sa.String(length=20), nullable=False),
        sa.Column("EXECUTED_AT", sa.DateTime(timezone=True), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["COURSE_ID"], ["ET_COURSE.COURSE_ID"], name="FK_ET_OWNER_TRANSFER_COURSE"),
        sa.PrimaryKeyConstraint("TRANSFER_ID", name="PK_ET_OWNER_TRANSFER"),
    )
    op.create_index("IX_ET_OWNER_TRANSFER_COURSE", "ET_OWNER_TRANSFER", ["COURSE_ID"], unique=False)
