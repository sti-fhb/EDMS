"""dm_seed_review_reminder_schedule

Revision ID: a1c8e6f4b920
Revises: e7c3a9d21b46
Create Date: 2026-08-19 14:00:00.000000

US6 FR-006 簽核催辦每日批次：於 DP_SCHEDULE 註冊 SCHDM002（每日 08:00），HANDLER_REF 指向
app.dm.review.reminder.run；平台排程引擎啟動時載入。與 SCHDM001（DM KPI 週報 + 未讀提醒、週一）為不同 job。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1c8e6f4b920"
down_revision: Union[str, None] = "e7c3a9d21b46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JOB_ID = "SCHDM002"
_ROW = {
    "JOB_ID": _JOB_ID,
    "JOB_NAME": "DM 簽核催辦（送審停留逾門檻每日提醒）",
    "MODULE": "DM",
    "CRON_EXPR": "0 8 * * *",
    "HANDLER_REF": "app.dm.review.reminder.run",
    "IS_ENABLED": True,
}


def upgrade() -> None:
    op.execute(
        sa.text(
            'INSERT INTO "DP_SCHEDULE" '
            '("JOB_ID", "JOB_NAME", "MODULE", "CRON_EXPR", "HANDLER_REF", "IS_ENABLED", '
            '"CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:JOB_ID, :JOB_NAME, :MODULE, :CRON_EXPR, :HANDLER_REF, :IS_ENABLED, "
            "'system', now(), 0) ON CONFLICT (\"JOB_ID\") DO NOTHING"
        ).bindparams(**_ROW)
    )


def downgrade() -> None:
    op.execute(sa.text('DELETE FROM "DP_SCHEDULE" WHERE "JOB_ID" = :j').bindparams(j=_JOB_ID))
