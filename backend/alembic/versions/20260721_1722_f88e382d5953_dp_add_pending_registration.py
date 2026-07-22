"""dp_add_pending_registration

Revision ID: f88e382d5953
Revises: fd6f5608d0ed
Create Date: 2026-07-21 17:22:37.925470

新增待驗證註冊表 DP_PENDING_REGISTRATION 並 seed 註冊驗證信範本（US2 #56）。

異動說明：
- 建 DP_PENDING_REGISTRATION（TOKEN_HASH PK、EMAIL UNIQUE + 姓名 / 密碼雜湊 / 效期 + 標準欄位）：
  US2 改「Email 驗證後啟用」（方案 B）——未驗證註冊暫存於此、驗證通過才建 DP_USER。
- seed DP_NOTIFY_TEMPLATE「ACCOUNT_VERIFY」（MODULE=DP、IS_SYSTEM=true）：註冊驗證信範本，
  以參數化 INSERT + ON CONFLICT DO NOTHING（idempotent，不覆蓋管理者編輯）。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "f88e382d5953"
down_revision: Union[str, None] = "fd6f5608d0ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_VERIFY_BODY = (
    "{user_name} 您好：\n\n"
    "歡迎註冊 EDMS 教育訓練文件管理系統。請點擊以下連結完成 Email 驗證以啟用帳號：\n\n"
    "{verify_link}\n\n"
    "此連結將於 {expiry_minutes} 分鐘後失效。若非您本人操作，請忽略本信。\n\n"
    "— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
)


def upgrade() -> None:
    op.create_table(
        "DP_PENDING_REGISTRATION",
        sa.Column("TOKEN_HASH", sa.String(length=64), nullable=False),
        sa.Column("EMAIL", sa.String(length=255), nullable=False),
        sa.Column("USER_NAME", sa.String(length=50), nullable=False),
        sa.Column("PWD_HASH", sa.String(length=100), nullable=False),
        sa.Column("EXPIRES_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("RES_ID", sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint("TOKEN_HASH", name="PK_DP_PENDING_REGISTRATION"),
        sa.UniqueConstraint("EMAIL", name="UQ_DP_PENDING_REGISTRATION_EMAIL"),
    )

    # seed 註冊驗證信範本（參數化 + ON CONFLICT DO NOTHING）
    now = datetime.now(timezone.utc)
    stmt = text(
        'INSERT INTO "DP_NOTIFY_TEMPLATE" '  # noqa: S608 — 欄名為本檔常數，值走 bindparams
        '("MODULE", "TEMPLATE_CODE", "TEMPLATE_NAME", "SUBJECT", "BODY", "VARIABLES", '
        '"CHANNEL", "IS_ENABLED", "IS_SYSTEM", "VERSION", "CREATED_USER", "CREATED_DATE", "DELETED") '
        "VALUES (:module, :code, :name, :subject, :body, :variables, "
        ":channel, :is_enabled, :is_system, :version, :created_user, :created_date, :deleted) "
        'ON CONFLICT ("MODULE", "TEMPLATE_CODE") DO NOTHING'
    )
    op.execute(
        stmt.bindparams(
            module="DP",
            code="ACCOUNT_VERIFY",
            name="帳號註冊驗證",
            subject="【EDMS】帳號註冊驗證",
            body=_ACCOUNT_VERIFY_BODY,
            variables="user_name, verify_link, expiry_minutes",
            channel="EMAIL",
            is_enabled=True,
            is_system=True,
            version=1,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )


def downgrade() -> None:
    op.execute(
        text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = \'DP\' AND "TEMPLATE_CODE" = \'ACCOUNT_VERIFY\'')
    )
    op.drop_table("DP_PENDING_REGISTRATION")