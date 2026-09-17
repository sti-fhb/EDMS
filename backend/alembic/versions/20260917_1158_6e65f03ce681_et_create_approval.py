"""et_create_approval

Revision ID: 6e65f03ce681
Revises: ee1d5e46c3ad
Create Date: 2026-09-17 11:58:13.552766

建 `ET_APPROVAL`（線下考核核可紀錄，US16 / #352）——ET 模組的**第 29 張表**。

Foundation 的 `9aa92b82d0a0` 檔頭明文寫著「**不在本 migration**：`ET_APPROVAL`
（線下核可）屬 ET Issue #18，全模組共 29 張」，本 migration 補上該張。

**本 migration 只建一張表**：

- `ET_COURSE.REQUIRE_APPROVAL` 雖列於 T156，但已由 #202 隨 ET_COURSE 一併建立
  （`course/models.py`），此處不重複。
- `ET_APPROVAL_RESULT`（PASS / FAIL）**不建 lookup 表、不 seed**——2026-08-20 定案，
  本專案無 lookup 表機制，9 類代碼一律以應用層常數表達（`app/et/constants.py`）。
- 通知範本 `APPROVAL_PASSED` 已於 `c4e8f1a6d372` seed，此處不重複。

設計要點：

- `USER_ID` / `APPROVED_BY` / `REVOKED_BY` 為**邏輯 FK** 指向平台 `DP_USER`，
  依 ET 模組慣例**不設 DB 外鍵**（跨模組鬆耦合）；`COURSE_ID` 為同模組，設實體 FK。
- `UQ_ET_APPROVAL_COURSE_USER` 為**全表**唯一，**刻意不加 `postgresql_where`**
  ——見下方說明。
- `IX_ET_APPROVAL_USER` 供 US17（ET-19 核可查詢）依學員跨課程查詢；上方唯一鍵以
  `COURSE_ID` 為首欄，只給 `USER_ID` 的查詢用不到它。

🚨 **唯一鍵為何不排除 `IS_REVOKED`**

與 `ET_ENROLLMENT.UQ_ET_ENROLLMENT_USER_COURSE` 同一個形狀、同一個理由：`IS_REVOKED`
是**狀態開關**（這筆核可目前作不作數），不是 `DELETED`（這筆資料不存在了）。
`ET_CHAPTER` / `ET_ITEM` / `ET_SURVEY_QUESTION` 那幾次改成部分唯一索引，排除的都是
`DELETED`，與本表無關。

改成 `postgresql_where = "IS_REVOKED" = false` 會讓同一人同一課出現多列，直接推翻
`data-model` 的「0～1 筆 / 學員 / 課程」，而症狀是撤銷後重核靜默新建一列、
`REVOKE_*` 永遠留在舊列上。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e65f03ce681"
down_revision: Union[str, None] = "ee1d5e46c3ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ET_APPROVAL",
        sa.Column("APPROVAL_ID", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("COURSE_ID", sa.BigInteger(), nullable=False),
        sa.Column("USER_ID", sa.String(length=20), nullable=False),
        sa.Column("RESULT", sa.String(length=20), nullable=False),
        sa.Column("RESULT_NOTE", sa.Text(), nullable=True),
        sa.Column("IS_REVOKED", sa.Boolean(), nullable=False),
        sa.Column("REVOKE_REASON", sa.Text(), nullable=True),
        sa.Column("APPROVED_BY", sa.String(length=20), nullable=False),
        sa.Column("APPROVED_AT", sa.DateTime(timezone=True), nullable=False),
        sa.Column("REVOKED_BY", sa.String(length=20), nullable=True),
        sa.Column("REVOKED_AT", sa.DateTime(timezone=True), nullable=True),
        sa.Column("VERSION", sa.Integer(), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("DELETED", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["COURSE_ID"], ["ET_COURSE.COURSE_ID"], name="FK_ET_APPROVAL_COURSE"),
        sa.PrimaryKeyConstraint("APPROVAL_ID", name="PK_ET_APPROVAL"),
        sa.UniqueConstraint("COURSE_ID", "USER_ID", name="UQ_ET_APPROVAL_COURSE_USER"),
    )
    op.create_index("IX_ET_APPROVAL_USER", "ET_APPROVAL", ["USER_ID"], unique=False)


def downgrade() -> None:
    op.drop_index("IX_ET_APPROVAL_USER", table_name="ET_APPROVAL")
    op.drop_table("ET_APPROVAL")
