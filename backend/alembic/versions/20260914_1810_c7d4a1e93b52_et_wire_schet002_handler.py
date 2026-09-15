"""et wire schet002 handler (US14 / #325)

Revision ID: c7d4a1e93b52
Revises: b3e91c4a7d28
Create Date: 2026-09-14 18:10:00.000000

接上 SCHET002（到期自動關閉 + 結清逾期未提交之作答）handler 並啟用。

異動說明：
- 影響 Table：DP_SCHEDULE（更新 SCHET002 一列）、ET_QUIZ_ATTEMPT_M（新增 partial index）
- 新增 `IX_ET_ATTEMPT_IN_PROGRESS`（partial，`WHERE "STATUS"='IN_PROGRESS' AND "DELETED"=0`）：
  SCHET002 每日掃「仍未提交的作答」，而 `ET_QUIZ_ATTEMPT_M` 是 append-only、永不刪除，
  既有索引只有 `(USER_ID, QUIZ_ID)` 與 `(COURSE_ID)`，`STATUS` 無索引 → 該查詢等同每日
  全表掃 + 四層 JOIN，成本隨歷史作答量無上限成長。partial index 只收 `IN_PROGRESS` 的列
  （母體天然很小，因為作答完就離開這個狀態），體積不隨歷史成長。
- HANDLER_REF 由預留 placeholder `app.et.schedules.handlers.pending` 改為
  `app.et.schedules.handlers.daily_job`；IS_ENABLED 啟用（handler 已交付）。
  HANDLER_REF / MODULE 不可經排程編輯 API 修改（RCE 防護），故由 migration 接線
  （比照 DM 之 9eb4dd6e496b / a1c8e6f4b920）。
- CRON_EXPR 維持 `0 8 * * *`（每日 08:00）——SCHET002 無對應的時點參數
  （`ET_URGENT_REMIND_DAYS` 是業務門檻不是排程時點，由 handler 自行讀取）。
- DESCRIPTION 去掉「handler 待 ET-16 實作」並改述本次實際交付的職責；加急提醒屬
  ET-16 第二段（需逐學員進度聚合），故暫不列入。
- SCHET001 本次**不動**：其 handler 尚未交付，維持 IS_ENABLED = false。
- 皆為既有列之 UPDATE（不新增列），idempotent。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "c7d4a1e93b52"
down_revision: Union[str, None] = "b3e91c4a7d28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── SCHET002 接線值（US14 第一段）──
_HANDLER = "app.et.schedules.handlers.daily_job"
_DESCRIPTION = "每日 08:00 執行，關閉已逾閱課期間之課程，並結清這些課程中逾期未提交之作答（標 TIMEOUT 並計分）"

# 回滾用：DP #0 種子值（預留列）與 #311 設定的 DESCRIPTION
_HANDLER_OLD = "app.et.schedules.handlers.pending"
_DESCRIPTION_OLD = (
    "每日 08:00 執行，關閉已逾閱課期間之課程，並對截止前 ET_URGENT_REMIND_DAYS 天未完課者寄加急提醒"
    "（handler 待 ET-16 實作）"
)


def _update(handler: str, description: str, enabled: bool) -> None:
    op.execute(
        text(
            'UPDATE "DP_SCHEDULE" SET "HANDLER_REF" = :h, "DESCRIPTION" = :d, "IS_ENABLED" = :e '
            "WHERE \"JOB_ID\" = 'SCHET002'"
        ).bindparams(h=handler, d=description, e=enabled)
    )


_INDEX_NAME = "IX_ET_ATTEMPT_IN_PROGRESS"


def upgrade() -> None:
    _update(_HANDLER, _DESCRIPTION, True)
    op.create_index(
        _INDEX_NAME,
        "ET_QUIZ_ATTEMPT_M",
        ["ATTEMPT_ID"],
        postgresql_where=sa.text("\"STATUS\" = 'IN_PROGRESS' AND \"DELETED\" = 0"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="ET_QUIZ_ATTEMPT_M")
    _update(_HANDLER_OLD, _DESCRIPTION_OLD, False)
