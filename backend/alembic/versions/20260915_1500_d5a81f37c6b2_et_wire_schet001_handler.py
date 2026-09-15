"""et wire schet001 handler + drop weekly stat time param (US14 / #325)

Revision ID: d5a81f37c6b2
Revises: c7d4a1e93b52
Create Date: 2026-09-15 15:00:00.000000

接上 SCHET001（週統計快照 + 週報 + 每週未看提醒）handler 並啟用；同時收斂「執行時點」
的事實來源（SA Q1 裁示 A）。

異動說明：
- 影響 Table：DP_SCHEDULE（更新 SCHET001 一列）、DP_PARAM_M / DP_PARAM_D（刪 1 組參數）
- HANDLER_REF 由預留 placeholder `app.et.schedules.handlers.pending` 改為
  `app.et.schedules.handlers.weekly_job`；IS_ENABLED 啟用。HANDLER_REF / MODULE 不可經
  排程編輯 API 修改（RCE 防護），故由 migration 接線（比照 c7d4a1e93b52 / 9eb4dd6e496b）。
- CRON_EXPR 由 `0 8 * * 1` 改為 `0 10 * * 1`，對齊規格原訂之「每週一 10:00」。
- **移除 `DP_PARAM.ET_WEEKLY_STAT_DAY_TIME`**（主檔 + 明細）。

## 為何移除那個參數（SA Q1 裁示 A）

排程引擎只讀 `DP_SCHEDULE.CRON_EXPR`（`scheduler.py` 以 `CronTrigger.from_crontab`
註冊），**完全不讀 `DP_PARAM`**。而規格三處寫「時間由 `ET_WEEKLY_STAT_DAY_TIME` 控制」，
兩者的值原本還互相矛盾（08:00 vs `MON 10:00`）。

留著它的話，管理者在 DP 後台改那個參數會**完全沒有效果且無任何錯誤訊息**——與 #171 /
#307 同族的「改動靜默失效」。移除之後，能改時間的地方與被讀的地方合一（DP 後台
「排程管理」，`CRON_EXPR` 可編輯且經 `apply_job_change` 即時生效；ET 管理者對該頁的
存取權與參數頁相同，皆為 `require_any_module_admin()`）。

`ET_URGENT_REMIND_DAYS` **不動**：它是業務門檻不是排程時點，由 handler 自行讀取。

downgrade 會把參數種回並還原 cron 與 placeholder。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "d5a81f37c6b2"
down_revision: Union[str, None] = "c7d4a1e93b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

# ── SCHET001 接線值 ──
_HANDLER = "app.et.schedules.handlers.weekly_job"
_CRON = "0 10 * * 1"  # 每週一 10:00（規格原訂時點）
_DESCRIPTION = "每週一 10:00 執行，寫入開放中課程之週統計快照，並寄出學習進度週報與每週未看提醒"

# 回滾用：DP #0 種子值（預留列）與 #311 設定的 DESCRIPTION
_HANDLER_OLD = "app.et.schedules.handlers.pending"
_CRON_OLD = "0 8 * * 1"
_DESCRIPTION_OLD = "每週一 08:00 執行，寫入課程週統計快照並寄出學習進度週報（handler 待 ET-16 實作）"

# ── 被移除的參數（回滾用之原始 seed 值，取自 c4e8f1a6d372）──
_PARAM_ID = "ET_WEEKLY_STAT_DAY_TIME"
_PARAM_M_ROW = (_PARAM_ID, "每週統計與週報執行時間", "VALUE", False, "SCHET001 執行時點")
_PARAM_D_ROW = (_PARAM_ID, "VALUE", "MON 10:00", "每週執行時間", 1, True)


def _update_schedule(handler: str, cron: str, description: str, enabled: bool) -> None:
    op.execute(
        text(
            'UPDATE "DP_SCHEDULE" SET "HANDLER_REF" = :h, "CRON_EXPR" = :c, "DESCRIPTION" = :d, "IS_ENABLED" = :e '
            "WHERE \"JOB_ID\" = 'SCHET001'"
        ).bindparams(h=handler, c=cron, d=description, e=enabled)
    )


def upgrade() -> None:
    _update_schedule(_HANDLER, _CRON, _DESCRIPTION, True)
    # 先刪明細再刪主檔（FK 方向）
    op.execute(text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" = :p').bindparams(p=_PARAM_ID))
    op.execute(text('DELETE FROM "DP_PARAM_M" WHERE "PARAM_ID" = :p').bindparams(p=_PARAM_ID))


def downgrade() -> None:
    now = datetime.now(timezone.utc)
    op.execute(
        text(
            'INSERT INTO "DP_PARAM_M" ("PARAM_ID", "PARAM_NAME", "PARAM_TYPE", "DETAIL_LOCK", "DESCRIPTION", '
            '"CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:param_id, :param_name, :param_type, :detail_lock, :description, :user, :now, 0) "
            'ON CONFLICT ("PARAM_ID") DO NOTHING'
        ).bindparams(
            param_id=_PARAM_M_ROW[0],
            param_name=_PARAM_M_ROW[1],
            param_type=_PARAM_M_ROW[2],
            detail_lock=_PARAM_M_ROW[3],
            description=_PARAM_M_ROW[4],
            user=_SEED_USER,
            now=now,
        )
    )
    op.execute(
        text(
            'INSERT INTO "DP_PARAM_D" ("PARAM_ID", "PARAM_KEY", "PARAM_VALUE", "PARAM_NAME", "SORT_ORDER", '
            '"IS_ENABLED", "CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:param_id, :param_key, :param_value, :param_name, :sort_order, :is_enabled, :user, :now, 0) "
            'ON CONFLICT ("PARAM_ID", "PARAM_KEY") DO NOTHING'
        ).bindparams(
            param_id=_PARAM_D_ROW[0],
            param_key=_PARAM_D_ROW[1],
            param_value=_PARAM_D_ROW[2],
            param_name=_PARAM_D_ROW[3],
            sort_order=_PARAM_D_ROW[4],
            is_enabled=_PARAM_D_ROW[5],
            user=_SEED_USER,
            now=now,
        )
    )
    _update_schedule(_HANDLER_OLD, _CRON_OLD, _DESCRIPTION_OLD, False)
