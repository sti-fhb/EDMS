"""dp_email_log_redact_account_link_mails

Revision ID: b27739aa4ac6
Revises: 391ed0865ae6
Create Date: 2026-11-02 11:17:33.929327

遮罩已寄註冊驗證／邀請信內文並更新 SCHDP001 說明

回溯遮罩已寄出之註冊驗證信 / 邀請信 outbox 內文（#50 SA 2026-11-02 裁示 1），並把排程總覽
（DP06）上的 SCHDP001 說明補上本版新增的第④批（裁示 2）。

異動說明：
- 影響 Table：DP_EMAIL_LOG（僅 UPDATE 既有列之 BODY / UPDATED_*，不改 schema）
  - 範圍：STATUS='SENT' 且 (MODULE, TEMPLATE_CODE) 為 (DP, ACCOUNT_VERIFY) / (DP, ACCOUNT_INVITE)
  - PENDING 列不動（重試需原文）
- 影響 Table：DP_SCHEDULE（SCHDP001 一列之 DESCRIPTION）
  - 條件帶原值（34da4449e681 寫入之說明）比對，不覆蓋管理者於 DP06 改過的內容

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

- DP_EMAIL_LOG 遮罩**不可逆**：原文已覆寫、無從還原（亦不應還原——還原即重新寫入明文連結）。
- DP_SCHEDULE.DESCRIPTION 可還原：同樣帶新值比對，改回 34da4449e681 的說明。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "b27739aa4ac6"
down_revision: Union[str, None] = "391ed0865ae6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REDACTED_BODY = "[已遮罩：本信含一次性連結，寄出後清除原文]"

# SCHDP001 說明：(34da4449e681 寫入之原值, 新值)
_SCHDP001_DESC_OLD = (
    "停用連續閒置超過閒置停用天數未登入之帳號、對密碼即將到期者寄提醒信，並清理逾期未完成之註冊驗證資料"
)
_SCHDP001_DESC_NEW = (
    "停用連續閒置超過閒置停用天數未登入之帳號、對密碼即將到期者寄提醒信、"
    "清理逾期未完成之註冊驗證資料，並清除寄送失敗且連結已失效之信件內文"
)

_UPDATE_SCHEDULE_DESC = text(
    'UPDATE "DP_SCHEDULE" SET "DESCRIPTION" = :new WHERE "JOB_ID" = \'SCHDP001\' AND "DESCRIPTION" = :old'
)


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
    op.execute(_UPDATE_SCHEDULE_DESC.bindparams(new=_SCHDP001_DESC_NEW, old=_SCHDP001_DESC_OLD))


def downgrade() -> None:
    # DP_EMAIL_LOG 遮罩不可逆（見 module docstring），只還原 SCHDP001 說明
    op.execute(_UPDATE_SCHEDULE_DESC.bindparams(new=_SCHDP001_DESC_OLD, old=_SCHDP001_DESC_NEW))
