"""dp_schdp001_job_name_add_pending_purge

SCHDP001 加入第三批次「清理逾期待驗證列」（#226）後，`DP_SCHEDULE.JOB_NAME` 的原字串
（「平台每日作業（閒置帳號禁用 + 密碼到期提醒）」）已不完整。該欄位會顯示於排程總覽畫面
（US11 / DP09），管理者據此判斷這支 job 在做什麼，故一併更正而非留著誤導。

純資料更新，無 schema 異動。以 JOB_ID 定位單列；WHERE 另比對舊字串，使本 migration 在
JOB_NAME 已被手動改過的環境上不覆蓋他人的修改（idempotent，重跑無副作用）。

Revision ID: 070865346fb4
Revises: 8ce307803975
Create Date: 2026-08-27 15:57:48.293707

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "070865346fb4"
down_revision: Union[str, None] = "8ce307803975"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_NAME = "平台每日作業（閒置帳號禁用 + 密碼到期提醒）"
_NEW_NAME = "平台每日作業（閒置帳號禁用 + 密碼到期提醒 + 清理逾期待驗證列）"


def _rename(from_name: str, to_name: str) -> None:
    op.execute(
        sa.text('UPDATE "DP_SCHEDULE" SET "JOB_NAME" = :to WHERE "JOB_ID" = :job AND "JOB_NAME" = :from').bindparams(
            to=to_name, job="SCHDP001", **{"from": from_name}
        )
    )


def upgrade() -> None:
    _rename(_OLD_NAME, _NEW_NAME)


def downgrade() -> None:
    _rename(_NEW_NAME, _OLD_NAME)
