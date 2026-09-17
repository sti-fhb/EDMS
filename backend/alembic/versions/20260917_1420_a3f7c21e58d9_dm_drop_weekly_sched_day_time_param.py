"""dm drop weekly sched day time param (#332)

Revision ID: a3f7c21e58d9
Revises: ee1d5e46c3ad
Create Date: 2026-09-17 14:20:00.000000

移除 `DP_PARAM.DM_WEEKLY_SCHED_DAY_TIME`（主檔 + 明細），使排程執行時點的事實來源
在 DM 側也收斂為 `DP_SCHEDULE.CRON_EXPR`——與 ET 於 #325（`d5a81f37c6b2`）的處置一致。

異動說明：
- 影響 Table：`DP_PARAM_M` / `DP_PARAM_D`（各刪 1 列）
- 不動任何排程列：`SCHDM001` 的 `CRON_EXPR` 已於 `9eb4dd6e496b` 設為 `0 10 * * 1`

## 為何移除

平台排程引擎只讀 `DP_SCHEDULE.CRON_EXPR`（`app/dp/schedules/scheduler.py` 以
`CronTrigger.from_crontab` 註冊），**完全不讀 `DP_PARAM`**。該參數自 `b7fa4b6e4fe7`
種入以來**從未被任何程式讀取過**。

留著它的後果不是「功能缺了」，而是**管理者在 DP 後台「系統參數與清單」改那個值會完全
沒有效果，且沒有任何錯誤訊息**——與 #171（參數缺維護層級）、#307（通知 CHANNEL 改了
靜默失效）同一族：**設定改得動、後果看不見**。

## 這推翻了一條既有的 SA 裁示，理由如下

`docs/specs/dm/spec_us13.md` FR-004a 的 SA 裁示（2026-09-02，Q1=A）已認定執行時點的
單一事實來源是 `CRON_EXPR`，但選擇**保留該參數為「預設值紀錄、不參與實際排程決策」**。

本次（#332，2026-09-17 使用者裁示）推翻「保留」那一半，理由是：

1. **「預設值紀錄」沒有讀者。** 它不被引擎讀、不被 handler 讀、也不在任何文件產生流程
   中被讀。真正的預設值已寫進 `9eb4dd6e496b` 的 `_SCHDM001_CRON`
2. **它仍然出現在 DP 後台且看起來可編輯。** 「不參與決策」是寫在規格裡的，不是使用者
   看得到的——管理者面對的仍是一個改得動而無效的輸入框
3. **ET 與 DM 對同一問題給出不同答案，後人無從判斷哪個是對的。** ET 已於 #325 移除

## 不在本次範圍

`DM_REMIND_THRESHOLD`（催辦門檻天數）與 `ET_URGENT_REMIND_DAYS`（截止前幾天）**不動**
——它們是**業務門檻**而非排程時點，由各 handler 於執行時自行讀取，`DP_PARAM` 對它們
是正確且有效的事實來源。

## 回滾

`downgrade()` 以 `b7fa4b6e4fe7` 的原始 seed 值還原兩列（`ON CONFLICT DO NOTHING`）。
還原後該參數同樣不被任何程式讀取——回滾只恢復資料，不恢復「它有作用」這件事。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "a3f7c21e58d9"
down_revision: Union[str, Sequence[str], None] = "ee1d5e46c3ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_PARAM_ID = "DM_WEEKLY_SCHED_DAY_TIME"

# ── 回滾用之原始 seed 值（取自 b7fa4b6e4fe7）──
_PARAM_M_ROW = (
    _PARAM_ID,
    "每週排程執行時間",
    "VALUE",
    False,
    "KPI 週報 / 未讀提醒每週執行（星期,HH:MM），預設 週一,10:00",
)
_PARAM_D_ROW = (_PARAM_ID, "VALUE", "週一,10:00", "每週執行時間", 1, True)


def upgrade() -> None:
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
