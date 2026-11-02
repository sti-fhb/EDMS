"""dp_email_log_redact_account_link_mails

Revision ID: b27739aa4ac6
Revises: 7ade05c26fd8
Create Date: 2026-11-02 11:17:33.929327

回溯遮罩已寄出之註冊驗證信 / 邀請信 outbox 內文（#50 SA 2026-11-02 裁示 1）。

異動說明：
- 影響 Table：DP_EMAIL_LOG（僅 UPDATE 既有列之 BODY / UPDATED_*，不改 schema）
- 範圍：STATUS='SENT' 且 (MODULE, TEMPLATE_CODE) 為 (DP, ACCOUNT_VERIFY) / (DP, ACCOUNT_INVITE)
- PENDING 列不動（重試需原文）

## 為什麼要回溯

SA 裁示 ACCOUNT_VERIFY / ACCOUNT_INVITE 比照 04fc1cf07681（PWD_RESET / EMAIL_CHANGE_VERIFY）：
寄出（SENT）後遮罩 BODY。`dp/notify/worker.py` 自本版起於寄出成功時遮罩，但本 migration 之前
已寄出的列仍以明文保存啟用 / 驗證連結（`DpEmailLog` 永不刪除）。

遮罩字串須與 `app.dp.notify.redaction.REDACTED_BODY` 一致；此處寫死而不 import，避免 migration
隨應用程式碼日後變動而改變行為。

## 為什麼 FAILED 列不在此處理

裁示 2（FAILED 列超過連結時效後遮罩）由 SCHDP001 平台每日作業執行，判斷條件是「建立時間 + 該範本
的時效參數」——那是**每日掃描**而非事件觸發，部署後第一次執行就會涵蓋所有既有 FAILED 列。
在此重做一次需要在 SQL 內重讀 DP_PARAM 時效參數、複製同一份判斷，兩份規則日後會分歧。

## 部署順序

先換新版 backend（含 worker），再 `alembic upgrade`。反過來的話，本 migration 之後才由舊版
worker 轉 SENT 的列不會被遮罩。

## downgrade

不可逆：原文已覆寫、無從還原（亦不應還原——還原即重新寫入明文連結）。downgrade 為 no-op。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "b27739aa4ac6"
down_revision: Union[str, None] = "7ade05c26fd8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REDACTED_BODY = "[已遮罩：本信含一次性連結，寄出後清除原文]"


def upgrade() -> None:
    op.execute(
        text(
            'UPDATE "DP_EMAIL_LOG" '
            'SET "BODY" = :redacted, "UPDATED_USER" = \'SYSTEM\', "UPDATED_DATE" = now() '
            "WHERE \"STATUS\" = 'SENT' AND \"MODULE\" = 'DP' "
            "AND \"TEMPLATE_CODE\" IN ('ACCOUNT_VERIFY', 'ACCOUNT_INVITE') "
            'AND "BODY" <> :redacted'
        ).bindparams(redacted=_REDACTED_BODY)
    )


def downgrade() -> None:
    # 資料覆寫不可逆（見 module docstring），不實作
    pass
