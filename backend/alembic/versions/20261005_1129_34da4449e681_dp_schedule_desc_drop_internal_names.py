"""dp_schedule_desc_drop_internal_names

Revision ID: 34da4449e681
Revises: a57b8dc6d4db
Create Date: 2026-10-05 11:29:00.000000

把排程總覽（DP06）與系統參數頁說明欄裡的**內部識別字**換成使用者看得懂的詞。

畫面上原本寫「停用連續閒置超過 LOGIN.IDLE_DISABLE_DAYS 天未登入之帳號」「對送審停留逾
DM_REMIND_THRESHOLD 天之待簽核案件寄催辦提醒」「標 TIMEOUT 並計分」——參數代碼、狀態碼
是實作細節，看的人既查不到也不需要知道。改用該參數在系統參數頁的**中文名稱**
（「閒置停用天數」「催辦門檻天數」），使用者想調整時找得到對應的那一列。

異動說明：
- 影響 Table：`DP_SCHEDULE`（3 列之 `DESCRIPTION`）、`DP_PARAM_M`（1 列之 `DESCRIPTION`）
- 不改 schema、不新增 / 刪除列

| 項目 | 原本 | 改為 |
|---|---|---|
| SCHDP001 | `LOGIN.IDLE_DISABLE_DAYS` 天 | 閒置停用天數 |
| SCHDM002 | `DM_REMIND_THRESHOLD` 天 | 催辦門檻天數 |
| SCHET002 | 標 `TIMEOUT` 並計分 | 記為逾時並計分 |
| ET_URGENT_REMIND_DAYS | `SCHET002` 於訖止前 N 天寄… | 課程訖止前幾天，對未完課學員寄… |

SCHDP001 另把「待驗證列」改為「註冊驗證資料」——「列」是資料列的說法，同樣只有開發者
在用。

條件帶原值比對，不覆蓋他人改過的內容（排程說明於 DP06 可編輯）。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "34da4449e681"
down_revision: Union[str, None] = "a57b8dc6d4db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (JOB_ID, 原說明, 新說明)
_SCHEDULE_DESCRIPTIONS = (
    (
        "SCHDP001",
        (
            "停用連續閒置超過 LOGIN.IDLE_DISABLE_DAYS 天未登入之帳號、"
            "對密碼即將到期者寄提醒信，並清理逾期未完成之待驗證列"
        ),
        "停用連續閒置超過閒置停用天數未登入之帳號、對密碼即將到期者寄提醒信，並清理逾期未完成之註冊驗證資料",
    ),
    (
        "SCHDM002",
        "對送審停留逾 DM_REMIND_THRESHOLD 天之待簽核案件寄催辦提醒",
        "對送審停留逾催辦門檻天數之待簽核案件寄催辦提醒",
    ),
    (
        "SCHET002",
        "關閉已逾閱課期間之課程，並結清這些課程中逾期未提交之作答（標 TIMEOUT 並計分）",
        "關閉已逾閱課期間之課程，並結清這些課程中逾期未提交之作答（記為逾時並計分）",
    ),
)

# (PARAM_ID, 原說明, 新說明)
_PARAM_DESCRIPTIONS = (
    (
        "ET_URGENT_REMIND_DAYS",
        "SCHET002 於訖止前 N 天寄加急提醒",
        "課程訖止前幾天，對未完課學員寄加急提醒",
    ),
)

_UPDATE_SCHEDULE = text(
    'UPDATE "DP_SCHEDULE" SET "DESCRIPTION" = :new WHERE "JOB_ID" = :job_id AND "DESCRIPTION" = :old'
)
_UPDATE_PARAM = text(
    'UPDATE "DP_PARAM_M" SET "DESCRIPTION" = :new WHERE "PARAM_ID" = :param_id AND "DESCRIPTION" = :old'
)


def _apply(*, forward: bool) -> None:
    conn = op.get_bind()
    for job_id, old, new in _SCHEDULE_DESCRIPTIONS:
        before, after = (old, new) if forward else (new, old)
        conn.execute(_UPDATE_SCHEDULE.bindparams(new=after, job_id=job_id, old=before))
    for param_id, old, new in _PARAM_DESCRIPTIONS:
        before, after = (old, new) if forward else (new, old)
        conn.execute(_UPDATE_PARAM.bindparams(new=after, param_id=param_id, old=before))


def upgrade() -> None:
    _apply(forward=True)


def downgrade() -> None:
    _apply(forward=False)
