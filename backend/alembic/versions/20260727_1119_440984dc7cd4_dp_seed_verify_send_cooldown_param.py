"""dp_seed_verify_send_cooldown_param

Revision ID: 440984dc7cd4
Revises: e3f359da5d20
Create Date: 2026-07-27 11:19:43

補 seed：LOGIN.VERIFY_SEND_COOLDOWN_SEC（驗證信重寄冷卻秒數，#74 / #76）納入參數維護。

異動說明：
- 影響 Table：DP_PARAM_D
- #76 原以程式預設 600 讀取、未 seed row，導致無法於 US5 維護頁調整；本 migration 補一筆
  可維護的 row（值 600，與原預設一致 → 零行為變更），使之與其他 LOGIN 群組參數一致可調。
- ON CONFLICT DO NOTHING：若該 row 已存在（如手動補過）則不覆蓋。
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "440984dc7cd4"
down_revision: Union[str, None] = "e3f359da5d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.execute(
        text(
            'INSERT INTO "DP_PARAM_D" '
            '("PARAM_ID", "PARAM_KEY", "PARAM_NAME", "PARAM_VALUE", "IS_ENABLED", '
            '"CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:param_id, :param_key, :param_name, :param_value, :is_enabled, "
            ":created_user, :created_date, :deleted) "
            'ON CONFLICT ("PARAM_ID", "PARAM_KEY") DO NOTHING'
        ).bindparams(
            param_id="LOGIN",
            param_key="VERIFY_SEND_COOLDOWN_SEC",
            param_name="驗證信重寄冷卻（秒）",
            param_value="600",
            is_enabled=True,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )


def downgrade() -> None:
    op.execute(
        text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key').bindparams(
            param_id="LOGIN", param_key="VERIFY_SEND_COOLDOWN_SEC"
        )
    )
