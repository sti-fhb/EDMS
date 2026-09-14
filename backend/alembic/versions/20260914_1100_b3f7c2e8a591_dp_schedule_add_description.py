"""dp_schedule_add_description

Revision ID: b3f7c2e8a591
Revises: cb17257ddf60
Create Date: 2026-09-14 11:00:00.000000

DP_SCHEDULE 新增 DESCRIPTION 欄位並拆短 JOB_NAME（#311，對齊 TBMS 之 DP_SCHEDULE）。

異動說明：
- 影響 Table：DP_SCHEDULE（新增 DESCRIPTION VARCHAR(200) NULL）
- 回填五筆既有 job 之 DESCRIPTION，並把工作內容細節從 JOB_NAME 移入說明欄
- 原本沒有說明欄，管理者只能靠 JOB_NAME 判斷 job 在做什麼（該欄顯示於 US11 / DP09
  排程總覽），SCHDP001 因此被塞成「平台每日作業（閒置帳號禁用 + 密碼到期提醒 +
  清理逾期待驗證列）」——每次工作內容變動都得改那串字並開一支 migration（070865346fb4）
- nullable：既有列先以 UPDATE 回填，不加 NOT NULL 約束（新 job 可暫不填說明）
- JOB_NAME 之 UPDATE 另比對舊字串（比照 070865346fb4），使本 migration 在 JOB_NAME
  已被手動改過的環境上不覆蓋他人的修改；重跑無副作用
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f7c2e8a591"
down_revision: Union[str, None] = "cb17257ddf60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (JOB_ID, 舊 JOB_NAME, 新 JOB_NAME, DESCRIPTION)
# 文案格式對齊 TBMS：JOB_NAME 為短名詞、DESCRIPTION 為「{頻率}執行，{動作與受影響的資料}」。
_JOBS: list[tuple[str, str, str, str]] = [
    (
        "SCHDP001",
        "平台每日作業（閒置帳號禁用 + 密碼到期提醒 + 清理逾期待驗證列）",
        "平台每日作業",
        "每日 08:00 執行，停用連續閒置超過 LOGIN.IDLE_DISABLE_DAYS 天未登入之帳號、"
        "對密碼即將到期者寄提醒信，並清理逾期未完成之待驗證列",
    ),
    (
        "SCHDM001",
        "DM KPI 週報 + 未讀提醒（預留）",
        "DM 週報與未讀提醒",
        "每週一 08:00 執行，寄出文件閱讀率 KPI 週報予 DM 管理者，並對應看未看者寄未讀提醒",
    ),
    (
        "SCHDM002",
        "DM 簽核催辦（送審停留逾門檻每日提醒）",
        "DM 簽核催辦",
        "每日 08:00 執行，對送審停留逾 DM_REMIND_THRESHOLD 天之待簽核案件寄催辦提醒",
    ),
    (
        "SCHET001",
        "ET 週報 / 提醒（預留）",
        "ET 週統計與週報",
        "每週一 08:00 執行，寫入課程週統計快照並寄出學習進度週報（handler 待 ET-16 實作）",
    ),
    (
        "SCHET002",
        "ET 到期關閉 + 加急提醒（預留）",
        "ET 到期關閉與加急提醒",
        "每日 08:00 執行，關閉已逾閱課期間之課程，並對截止前 ET_URGENT_REMIND_DAYS 天"
        "未完課者寄加急提醒（handler 待 ET-16 實作）",
    ),
]

_SET_DESC = sa.text('UPDATE "DP_SCHEDULE" SET "DESCRIPTION" = :description WHERE "JOB_ID" = :job_id')
_RENAME = sa.text(
    'UPDATE "DP_SCHEDULE" SET "JOB_NAME" = :new_name WHERE "JOB_ID" = :job_id AND "JOB_NAME" = :old_name'
)


def upgrade() -> None:
    op.add_column("DP_SCHEDULE", sa.Column("DESCRIPTION", sa.String(length=200), nullable=True))
    for job_id, old_name, new_name, description in _JOBS:
        op.execute(_SET_DESC.bindparams(description=description, job_id=job_id))
        op.execute(_RENAME.bindparams(new_name=new_name, job_id=job_id, old_name=old_name))


def downgrade() -> None:
    # 先還原 JOB_NAME（同樣比對字串），再移除欄位——欄位一旦 drop，DESCRIPTION 內容即消失。
    for job_id, old_name, new_name, _ in _JOBS:
        op.execute(_RENAME.bindparams(new_name=old_name, job_id=job_id, old_name=new_name))
    op.drop_column("DP_SCHEDULE", "DESCRIPTION")
