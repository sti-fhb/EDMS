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

## 不回填既有列（使用者裁示 2026-10-16）

既有廢止退回列的退回原因只在 `DP_AUDIT_LOG.after_value.reject_reason`。**不回填**，理由：

1. 回填要解析稽核的 JSON，而那個形狀**不是契約**
2. 跨模組讀 DP 表
3. dev DB 上零命中 ⇒ **零證據、不是弱證據**，無法驗證回填在正式資料上的行為

舊列的 `REJECT_REASON` 為 NULL，畫面顯示「—」；管理者仍可自 DP05 操作記錄查到。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0d17180b7546"
down_revision: Union[str, None] = "9c83bd25a9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "DM_REVIEW"
_COLUMN = "REJECT_REASON"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, _COLUMN)
