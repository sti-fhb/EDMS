"""dp_param_d_add_param_name_desc

Revision ID: e3f359da5d20
Revises: f88e382d5953
Create Date: 2026-07-24 15:47:14

DP_PARAM_D 補中文顯示名稱與說明（US5 對齊 TBMS，SA 裁示 Q1=A/Q2=A）。

異動說明：
- 影響 Table：DP_PARAM_D
- PARAM_NAME：VARCHAR(100)、NOT NULL（中文顯示名稱，取代前端硬編碼；分三步加）
- DESCRIPTION：VARCHAR(500)、NULL（明細補充說明）
- 回填既有 21 筆種子：VALUE 明細填中文名稱、ACTION_TYPE（LIST）名稱由 PARAM_VALUE 遷入 PARAM_NAME 並清空 PARAM_VALUE（改專職值）
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "e3f359da5d20"
down_revision: Union[str, None] = "f88e382d5953"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 既有 VALUE 明細之中文名稱（對齊 spec_us5 §參數型別 / 值域驗證規則）。
_VALUE_NAMES: dict[tuple[str, str], str] = {
    ("JWT", "ACCESS_TTL_MIN"): "閒置自動登出（分鐘）",
    ("JWT", "RENEW_MAX_HOURS"): "單次登入時效上限（小時）",
    ("PWD_POLICY", "MIN_LEN"): "密碼最小長度（一般使用者）",
    ("PWD_POLICY", "ADMIN_MIN_LEN"): "密碼最小長度（特權帳號）",
    ("PWD_POLICY", "CHAR_TYPES"): "字元組合要求（種類數）",
    ("PWD_POLICY", "HISTORY_COUNT"): "密碼歷史記憶次數",
    ("PWD_POLICY", "EXPIRY_DAYS"): "密碼最長效期（天）",
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS"): "密碼到期提醒天數（天）",
    ("LOGIN", "FAIL_LOCK_COUNT"): "登入失敗鎖定次數",
    ("LOGIN", "LOCK_MINUTES"): "帳號鎖定時間（分鐘）",
    ("LOGIN", "RESET_TOKEN_TTL_MIN"): "密碼重設連結有效時間（分鐘）",
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): "Email 變更驗證連結有效時間（分鐘）",
    ("LOGIN", "IDLE_DISABLE_DAYS"): "閒置停用天數（天）",
    ("MAIL", "RATE_PER_MIN"): "每分鐘寄信上限（封）",
    ("MAIL", "RETRY_MAX"): "寄信重試上限次數",
    ("MAIL", "RETRY_INTERVAL_MIN"): "寄信重試間隔（分鐘）",
}


def upgrade() -> None:
    # Step 1：先加 nullable 欄位（既有資料才能通過）
    op.add_column("DP_PARAM_D", sa.Column("PARAM_NAME", sa.String(100), nullable=True))
    op.add_column("DP_PARAM_D", sa.Column("DESCRIPTION", sa.String(500), nullable=True))

    conn = op.get_bind()
    # Step 2a：回填 VALUE 明細之中文名稱（SQL 本體靜態、值具名綁定，sti-alembic-rules）
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "PARAM_NAME" = :name WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key'
    )
    for (param_id, param_key), name in _VALUE_NAMES.items():
        conn.execute(stmt.bindparams(name=name, param_id=param_id, param_key=param_key))

    # Step 2b：ACTION_TYPE（LIST）名稱由 PARAM_VALUE 遷入 PARAM_NAME，PARAM_VALUE 清空（改專職值）
    conn.execute(
        text(
            'UPDATE "DP_PARAM_D" SET "PARAM_NAME" = "PARAM_VALUE", "PARAM_VALUE" = NULL WHERE "PARAM_ID" = :param_id'
        ).bindparams(param_id="ACTION_TYPE")
    )

    # Step 3：回填完成後設 NOT NULL
    op.alter_column("DP_PARAM_D", "PARAM_NAME", existing_type=sa.String(100), nullable=False)


def downgrade() -> None:
    # ACTION_TYPE 之 PARAM_VALUE 還原（名稱移回值），再移除新欄位
    op.execute(
        text('UPDATE "DP_PARAM_D" SET "PARAM_VALUE" = "PARAM_NAME" WHERE "PARAM_ID" = :param_id').bindparams(
            param_id="ACTION_TYPE"
        )
    )
    op.drop_column("DP_PARAM_D", "DESCRIPTION")
    op.drop_column("DP_PARAM_D", "PARAM_NAME")
