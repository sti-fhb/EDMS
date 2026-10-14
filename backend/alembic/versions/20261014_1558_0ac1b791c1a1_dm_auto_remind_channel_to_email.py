"""dm_auto_remind_channel_to_email

Revision ID: 0ac1b791c1a1
Revises: a3f9c21e5d84
Create Date: 2026-10-14 15:58:00.000000

簽核催辦改為真的寄 Email（#627 裁示 (b)）。

異動說明：
- 影響 Table：DP_NOTIFY_TEMPLATE（更新 1 列之 CHANNEL，不新增 / 不刪除列）
- AUTO_REMIND：MSG → EMAIL；downgrade 還原為 MSG
- 本次不改 SUBJECT / BODY / VARIABLES——錯位的是**程式傳入的 params key**
  （`waiting_days` → `days`），已於 `dm/review/center_service.py` 修正

## 為什麼要改（#627）

`SCHDM002` 每日排程自 2026-08-06 起每天執行，但**三個出口全部沒有產出**：

| 出口 | 為何沒有 |
|---|---|
| Email | `CHANNEL='MSG'` → `_channel_allows_email` 回 False → `queued_count=0` |
| 站內訊息 | SA 裁示 Q1「催辦免站內訊息表」，平台也沒有站內訊息佇列 |
| DB 痕跡 | 未排入 outbox，`DP_EMAIL_LOG` 無列 |

而 `scan_overdue_and_remind` 無條件 `count += 1`，所以排程 log 每天照報「催辦 N 筆」。
spec_us6 FR-006 是 MUST「每日自動催辦指定審核者」——該功能實際上從未運作過。

## ⚠️ 為何把 AUTO_REMIND 自 #554 的分類中取出

`15e30a8f8b6f`（#554）依「收件人是不是送審當事人」把 5 支流程通知改為 MSG，並把
AUTO_REMIND 歸在同一類；其立論是**當事人在畫面上看得到**（我的文件動態 / 簽核中心）。

該立論對那 5 支成立、對催辦**剛好相反**：

| | 那 5 支（DOC_SUBMIT / DOC_REJECT / OBS_*）| AUTO_REMIND |
|---|---|---|
| 觸發時機 | 事件**剛發生** | 事件發生後**已逾門檻天數沒有動作** |
| 隱含前提 | 收件人接下來本來就會進畫面處理 | 收件人**已經很久沒進畫面** |

亦即：那 5 支是「你等一下會來看，所以不必寄」，催辦是「你已經沒在看了」——同一條原則
套到催辦上會自我否定。`SUBMIT_WITHDRAWN` 維持 MSG，它屬「事件剛發生」那一類。

此例外亦寫於 `tests/integration/dm/test_dm_dp_seed.py::test_dm_template_channels` 的
docstring（該測試是守著分類的那道門）。

## 連帶效果：此範本自本次起出現在 DP04

`dp/notify/admin_service.py` 的 `_MAINTAINABLE_CHANNELS = ("EMAIL", "BOTH")` 會過濾掉
MSG 範本——這正是先前在 DP04 看不到催辦範本的原因。改為 EMAIL 後它會自動出現、
管理者可編輯主旨與內文（CHANNEL 本身唯讀，#307）。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "0ac1b791c1a1"
down_revision: Union[str, None] = "a3f9c21e5d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEMPLATE = "AUTO_REMIND"
_NEW_CHANNEL = "EMAIL"
_OLD_CHANNEL = "MSG"  # 回滾用：b7fa4b6e4fe7 之種子值


def _set_channel(channel: str) -> None:
    """設定催辦範本之 CHANNEL（MODULE 限 DM，避免誤觸同名他模組範本）。"""
    op.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "CHANNEL" = :channel '
            'WHERE "MODULE" = \'DM\' AND "TEMPLATE_CODE" = :code'
        ).bindparams(channel=channel, code=_TEMPLATE)
    )


def upgrade() -> None:
    _set_channel(_NEW_CHANNEL)


def downgrade() -> None:
    _set_channel(_OLD_CHANNEL)
