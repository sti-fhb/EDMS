"""dp_pending_reg_add_kind_and_invite_template

Revision ID: 58d4121e3efb
Revises: f88e382d5953
Create Date: 2026-07-23 13:56:35.533505

DP_PENDING_REGISTRATION 加 KIND 欄、PWD_HASH 改可空，並 seed 邀請信範本。

異動說明（US4 #67 代建改邀請流程）：
- 影響 Table：DP_PENDING_REGISTRATION、DP_NOTIFY_TEMPLATE
- 新增 KIND VARCHAR(20) NOT NULL：區分 SELF_REGISTER（US2 自助註冊）/ ADMIN_INVITE（US4 邀請）；
  既有列皆為自助註冊，回填 SELF_REGISTER（三步驟 ADD NOT NULL，相容舊資料）
- PWD_HASH 改為 nullable：ADMIN_INVITE 建立時無密碼，使用者啟用時自設回填
- seed DP_NOTIFY_TEMPLATE「ACCOUNT_INVITE」（MODULE=DP、IS_SYSTEM=true）：邀請信範本，
  文案為「管理者已為您建立帳號，請設定密碼」（不沿用 ACCOUNT_VERIFY 之「歡迎註冊」語意）
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "58d4121e3efb"
down_revision: Union[str, None] = "f88e382d5953"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_INVITE_BODY = (
    "{user_name} 您好：\n\n"
    "系統管理者已為您建立 EDMS 教育訓練文件管理系統帳號。"
    "請點擊以下連結設定您的密碼以啟用帳號並登入：\n\n"
    "{activate_link}\n\n"
    "此連結將於 {expiry_minutes} 分鐘後失效。若您不認識本系統，請忽略本信。\n\n"
    "— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
)


def upgrade() -> None:
    # 1. 加 KIND 欄（先 nullable → 回填 → 設 NOT NULL，相容既有資料）
    op.add_column("DP_PENDING_REGISTRATION", sa.Column("KIND", sa.String(length=20), nullable=True))
    op.execute(
        text('UPDATE "DP_PENDING_REGISTRATION" SET "KIND" = :kind WHERE "KIND" IS NULL').bindparams(
            kind="SELF_REGISTER"
        )
    )
    op.alter_column("DP_PENDING_REGISTRATION", "KIND", nullable=False)

    # 2. PWD_HASH 改可空（ADMIN_INVITE 建立時無密碼）
    op.alter_column("DP_PENDING_REGISTRATION", "PWD_HASH", existing_type=sa.String(length=100), nullable=True)

    # 3. seed 邀請信範本（參數化 + ON CONFLICT DO NOTHING，不覆蓋既有）
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
            code="ACCOUNT_INVITE",
            name="帳號邀請",
            subject="【EDMS】帳號邀請：請設定密碼以啟用",
            body=_ACCOUNT_INVITE_BODY,
            variables="user_name, activate_link, expiry_minutes",
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
        text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c').bindparams(
            m="DP", c="ACCOUNT_INVITE"
        )
    )
    # PWD_HASH 還原 NOT NULL 前，ADMIN_INVITE（PWD_HASH IS NULL）列無法保留，先清除之
    op.execute(text('DELETE FROM "DP_PENDING_REGISTRATION" WHERE "KIND" = :k').bindparams(k="ADMIN_INVITE"))
    op.alter_column("DP_PENDING_REGISTRATION", "PWD_HASH", existing_type=sa.String(length=100), nullable=False)
    op.drop_column("DP_PENDING_REGISTRATION", "KIND")
