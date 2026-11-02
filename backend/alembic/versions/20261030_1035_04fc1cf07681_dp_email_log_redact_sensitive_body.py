"""dp_email_log_redact_sensitive_body

Revision ID: 04fc1cf07681
Revises: 18489e30023b
Create Date: 2026-10-30 10:35:10.727045

回溯遮罩已寄出敏感系統信之 outbox 內文（#50）。

異動說明：
- 影響 Table：DP_EMAIL_LOG（僅 UPDATE 既有列之 BODY / UPDATED_*，不改 schema）
- 範圍：STATUS='SENT' 且 (MODULE, TEMPLATE_CODE) 為 (DP, PWD_RESET) / (DP, EMAIL_CHANGE_VERIFY)
- PENDING / FAILED 列不動（與 worker 行為一致：PENDING 需原文供重試；FAILED 依 SA 裁示保留）

## 為什麼要回溯

#50 SA 裁示方案 A：上述兩種系統信寄出（SENT）後遮罩 BODY。`dp/notify/worker.py` 自本版
起於寄出成功時遮罩，但**本 migration 之前已寄出的列**仍以明文保存重設 / 驗證連結
（`DpEmailLog` 永不刪除），只改 worker 等於把既有暴露面原樣留在庫裡。

遮罩字串須與 `app.dp.notify.worker.REDACTED_BODY` 一致；此處寫死而不 import，
避免 migration 隨應用程式碼日後變動而改變行為。

## downgrade

不實作：原文已覆寫、無從還原（亦不應還原——還原即重新寫入明文連結）。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "04fc1cf07681"
down_revision: Union[str, None] = "18489e30023b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REDACTED_BODY = "[已遮罩：本信含一次性連結，寄出後清除原文]"


def upgrade() -> None:
    op.execute(
        text(
            'UPDATE "DP_EMAIL_LOG" '
            'SET "BODY" = :redacted, "UPDATED_USER" = \'SYSTEM\', "UPDATED_DATE" = now() '
            'WHERE "STATUS" = \'SENT\' AND "MODULE" = \'DP\' '
            'AND "TEMPLATE_CODE" IN (\'PWD_RESET\', \'EMAIL_CHANGE_VERIFY\') '
            'AND "BODY" <> :redacted'
        ).bindparams(redacted=_REDACTED_BODY)
    )


def downgrade() -> None:
    # 資料覆寫不可逆（見 module docstring），不實作
    pass
