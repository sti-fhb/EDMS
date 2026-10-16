"""dm_review_add_reject_reason

Revision ID: 0d17180b7546
Revises: 9c83bd25a9b2
Create Date: 2026-10-16 14:20:00.000000

`DM_REVIEW` 新增 `REJECT_REASON`：審核者退回時填寫的原因（#679）。

異動說明：
- 影響 Table：DM_REVIEW（新增 1 欄，nullable，不回填）
- downgrade 移除該欄

## 為什麼需要一個新欄位

`REASON` **一欄兩義**：

| review_type | REASON 的內容 | 誰寫的 |
|---|---|---|
| NEW / NEW_VERSION | 退回原因 | 審核者 |
| OBSOLETE | **廢止申請原因** | 申請人 |

OBSOLETE 那一列是刻意的：`review/center_service._reject_obsolete` 在 `reject()`（會覆寫
`REASON`）之後**把申請人的原始廢止原因寫回**，因為那是廢止申請理由**唯一的存放處**，覆寫
將永久失去可追溯性。

結果是審核者對廢止申請寫的退回原因**沒有欄位可放**——只進了稽核（`after_value.reject_reason`）
與 `OBS_REJECT` 通知，而該通知自 #554 起是 `MSG`、本系統沒有站內訊息畫面。申請人因此在
DM04 與 DM02 都只看得到「—」（#679）。

## 設計：不分 review_type 一律寫入

`reviews.reject()` 對**所有**類型都寫 `REJECT_REASON`，語意唯一＝「審核者寫的退回原因」。
`REASON` 因而回歸單一語意（OBSOLETE 的申請理由）。

過渡期間 NEW / NEW_VERSION 的退回原因會同時存在於兩欄，這是刻意的取捨：讀取端只讀新欄位，
舊欄位留著是因為既有列的資料在那裡，且 `REASON` 對 OBSOLETE 仍有獨立用途。

## 既有列：非廢止回填、廢止不回填

兩類舊列的處境**完全不同**，不可一概而論（初版 docstring 把廢止的理由推廣到全部，錯了）：

| 舊列類型 | 退回原因在哪 | 處置 |
|---|---|---|
| `NEW` / `NEW_VERSION` | **同一張表的 `REASON`**（該欄對非廢止本來就是審核者寫的）| ✅ **回填** |
| `OBSOLETE` | 只在 `DP_AUDIT_LOG.after_value.reject_reason` | ❌ 不回填 |

**非廢止必須回填**，否則讀取端改讀 `REJECT_REASON` 之後，migration 之前的每一筆退回都會變成
「—」——資料還在 `REASON`，但**沒有任何讀取端**，正是 #554 / #657 要消滅的那個形狀在舊資料上
重演。影響最大的是 DM02「已完成」：它**沒有時間窗**，審核者過去所有退回紀錄會一次全消失。
回填是同表 UPDATE，不解析 JSON、不跨模組，三條「不回填」的理由對它一條都不成立。

**廢止不回填**（使用者裁示 2026-10-16）：

1. 回填要解析稽核的 JSON，而那個形狀**不是契約**
2. 跨模組讀 DP 表
3. dev DB 上零命中 ⇒ **零證據、不是弱證據**，無法驗證回填在正式資料上的行為

⚠️ 廢止舊列的退回原因**只能**由管理者自 DP05 查到（`_reject_obsolete` 的稽核有寫
`reject_reason`）。**非廢止的舊列在 DP05 查不到**——一般退回的稽核是
`after={"review_id": …, "operation": "REJECT"}`，不含 reason。這也是非廢止非回填不可的原因。

## ⚠️ downgrade 會永久刪除資料

`drop_column` 會把 upgrade 之後累積的所有審核者退回原因刪掉。對 `OBSOLETE` 列**無處可還原**
（`REASON` 裝的是申請人的理由）；非廢止列因為 `REASON` 仍有同一份值，影響較小。
降級前請自行備份該欄。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "0d17180b7546"
down_revision: Union[str, None] = "9c83bd25a9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "DM_REVIEW"
_COLUMN = "REJECT_REASON"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))
    # 回填**非廢止**的既有退回列：那些列的 `REASON` 本來就是審核者寫的退回原因，不回填會讓
    # 它們在讀取端改讀新欄位後一次全變「—」（詳見本檔 docstring）。
    # ⛔ `REVIEW_TYPE <> 'OBSOLETE'` 不可省：廢止列的 `REASON` 是**申請人**寫的申請理由，
    # 回填進來會把它當成審核者的退回原因顯示——那是錯的資訊，不是補齊。
    op.execute(
        text(
            'UPDATE "DM_REVIEW" SET "REJECT_REASON" = "REASON" '
            'WHERE "STATUS" = \'REJECTED\' AND "REVIEW_TYPE" <> \'OBSOLETE\' AND "REASON" IS NOT NULL'
        )
    )


def downgrade() -> None:
    op.drop_column(_TABLE, _COLUMN)
