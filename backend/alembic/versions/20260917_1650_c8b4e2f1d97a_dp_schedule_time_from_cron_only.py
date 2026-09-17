"""dp schedule time from cron only (#332)

Revision ID: c8b4e2f1d97a
Revises: a3f7c21e58d9
Create Date: 2026-09-17 16:50:00.000000

把「執行時點」從 `DP_SCHEDULE.DESCRIPTION` 移除，使它在畫面上也只有 `CRON_EXPR` 一個
來源；並修正兩支週報**實際跑在週二**的 cron。

異動說明：
- 影響 Table：`DP_SCHEDULE`（5 列改 `DESCRIPTION`、2 列改 `CRON_EXPR`）
- 不新增 / 不刪除任何列，不動 schema

## 一、兩支週報的 cron 實際落在週二（行為修正）

`SCHDM001` 與 `SCHET001` 的 `CRON_EXPR` 都是 `0 10 * * 1`，而規格、說明欄、已於
`a3f7c21e58d9` 移除的 `DM_WEEKLY_SCHED_DAY_TIME`（`週一,10:00`）、`d5a81f37c6b2` 的
`_CRON = "0 10 * * 1"  # 每週一 10:00（規格原訂時點）` 全都寫「週一」。

但引擎用的是 `CronTrigger.from_crontab`，而 **APScheduler 的 day-of-week 以週一為 0**，
它不做標準 crontab（週日為 0）的轉換：

    0 -> 週一   1 -> 週二   2 -> 週三 ...  6 -> 週日

旁證是 `7` 會被直接拒絕（`ValueError: the last value (7) is higher than the maximum
value (6)`），而標準 crontab 接受 7 為週日。

所以 `0 10 * * 1` 跑的是**週二**——兩支週報整整晚一天，且沒有任何測試釘住觸發日，
也沒有任何錯誤訊息。本支改為 `0 10 * * 0`。

**只改仍等於舊種子值的列**（`WHERE "CRON_EXPR" = '0 10 * * 1'`）：`CRON_EXPR` 是管理者
可於 DP 後台編輯的欄位，無條件覆寫會吃掉人為的刻意調整。

## 二、說明欄不再承載執行時點（收斂事實來源）

五筆 `DESCRIPTION` 原本都以「每日 08:00 執行，」「每週一 10:00 執行，」開頭，而
`CRON_EXPR` 可由管理者在**同一個畫面**上改——兩者沒有任何機制保持同步。

這不是假設性風險，已經歪過一次：`SCHDM001` 的 cron 於 `9eb4dd6e496b`（09-02）改為
`0 10 * * 1`，12 天後回填說明欄的 `b3f7c2e8a591`（09-14）抄的仍是舊的 `08:00`，於是
畫面上那行字從那天起就是假的。

改法是移除時點字樣、只留職責，時點改由前端從 `CRON_EXPR` 現算（`frontend/src/dp/
schedules/cron.ts`）。`DESCRIPTION` 不在後台可編輯欄位內（US11 僅開放 JOB_NAME /
CRON_EXPR / IS_ENABLED），故此處無條件覆寫。

## 回滾

`downgrade()` 還原兩者。還原後說明欄會再次寫死時點，且 `SCHDM001` 會回到那個已知
與 cron 矛盾的 `08:00` 字串——回滾恢復的是舊資料，不是舊資料的正確性。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c8b4e2f1d97a"
down_revision: Union[str, Sequence[str], None] = "a3f7c21e58d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SET_DESC = sa.text('UPDATE "DP_SCHEDULE" SET "DESCRIPTION" = :description WHERE "JOB_ID" = :job_id')
_SET_CRON = sa.text(
    'UPDATE "DP_SCHEDULE" SET "CRON_EXPR" = :new WHERE "JOB_ID" = :job_id AND "CRON_EXPR" = :old'
)

# (JOB_ID, 新 DESCRIPTION（只描述職責）, 舊 DESCRIPTION（含時點，回滾用）)
_DESCRIPTIONS: list[tuple[str, str, str]] = [
    (
        "SCHDP001",
        "停用連續閒置超過 LOGIN.IDLE_DISABLE_DAYS 天未登入之帳號、"
        "對密碼即將到期者寄提醒信，並清理逾期未完成之待驗證列",
        "每日 08:00 執行，停用連續閒置超過 LOGIN.IDLE_DISABLE_DAYS 天未登入之帳號、"
        "對密碼即將到期者寄提醒信，並清理逾期未完成之待驗證列",
    ),
    (
        "SCHDM001",
        "寄出文件閱讀率 KPI 週報予 DM 管理者，並對應看未看者寄未讀提醒",
        "每週一 08:00 執行，寄出文件閱讀率 KPI 週報予 DM 管理者，並對應看未看者寄未讀提醒",
    ),
    (
        "SCHDM002",
        "對送審停留逾 DM_REMIND_THRESHOLD 天之待簽核案件寄催辦提醒",
        "每日 08:00 執行，對送審停留逾 DM_REMIND_THRESHOLD 天之待簽核案件寄催辦提醒",
    ),
    (
        "SCHET001",
        "寫入開放中課程之週統計快照，並寄出學習進度週報與每週未看提醒",
        "每週一 10:00 執行，寫入開放中課程之週統計快照，並寄出學習進度週報與每週未看提醒",
    ),
    (
        "SCHET002",
        "關閉已逾閱課期間之課程，並結清這些課程中逾期未提交之作答（標 TIMEOUT 並計分）",
        "每日 08:00 執行，關閉已逾閱課期間之課程，並結清這些課程中逾期未提交之作答（標 TIMEOUT 並計分）",
    ),
]

# 週報：dow 1 實際是週二，改為 0（週一）。
_WEEKLY_CRON_OLD = "0 10 * * 1"
_WEEKLY_CRON_NEW = "0 10 * * 0"
_WEEKLY_JOBS = ("SCHDM001", "SCHET001")


def upgrade() -> None:
    for job_id, new_desc, _old in _DESCRIPTIONS:
        op.execute(_SET_DESC.bindparams(job_id=job_id, description=new_desc))
    for job_id in _WEEKLY_JOBS:
        op.execute(_SET_CRON.bindparams(job_id=job_id, old=_WEEKLY_CRON_OLD, new=_WEEKLY_CRON_NEW))


def downgrade() -> None:
    for job_id in _WEEKLY_JOBS:
        op.execute(_SET_CRON.bindparams(job_id=job_id, old=_WEEKLY_CRON_NEW, new=_WEEKLY_CRON_OLD))
    for job_id, _new, old_desc in _DESCRIPTIONS:
        op.execute(_SET_DESC.bindparams(job_id=job_id, description=old_desc))
