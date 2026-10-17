"""dm_auto_remind_aggregate_per_reviewer

Revision ID: 7c4e19ab3f52
Revises: 0d17180b7546
Create Date: 2026-10-17 11:30:00.000000

`AUTO_REMIND` 由「一份文件一封」改為「一位審核者一封彙整信」（#699）。

## 為何要改

催辦先前是逐筆寄（`ReviewCenterService.scan_overdue_and_remind` 對每一列 `notify` 一次），
一位審核者手上有 N 筆逾期就是每天收到 N 封各自只講一份文件的信。#627 把 `CHANNEL` 由
`MSG` 改成 `EMAIL` 之後，這個形狀才開始真的產生信件。

彙整形狀照抄同模組的 `UNREAD_REMIND`（未讀提醒，`{viewer_name}/{unread_count}/{unread_list}`）。

| | 舊 | 新 |
|---|---|---|
| VARIABLES | `reviewer_name,doc_name,days` | `reviewer_name,pending_count,pending_list` |
| 粒度 | 一份文件 | 一位審核者的全部逾期件 |

## 🔴 為何是無條件 UPDATE（背離 `a3f9c21e5d84` 的慣例）

`a3f9c21e5d84`（ET 廢止信文案）建立的慣例是 `WHERE "BODY" = :old`——**只更新仍是出廠
文字的列**，不覆寫管理者在 DP04 改過的內容。`AUTO_REMIND` 的 `IS_SYSTEM` 只擋停用
（`dp/notify/admin_service.py` 的 `if template.is_system and not data.is_enabled`），
不擋編輯主旨 / 內文，所以管理者確實可能動過它。

但本次改的**不是用字，是佔位詞彙**。若照慣例只更新出廠列，管理者改過的那一列會停在
`{doc_name}` / `{days}`，而程式自本次起只傳 `pending_count` / `pending_list`：

    _SafeFormatter 缺 key → KeyError → send_email 整批寫 FAILED 空信 → queued_count=0 → 不外拋

那正是 #627 讓催辦靜默停擺兩個月的同一個故障形狀。**「保留管理者用字」換來「催辦完全
不寄且無訊號」，後者嚴重得多**，故本次無條件覆寫，並接受管理者的自訂文案被重設。

## 🔴 為何要遞增 `VERSION`（與 `a3f9c21e5d84` 的 📌 相反）

初版照抄了 `a3f9c21e5d84` 的「📌 不動 `VERSION`：它記的是使用者編輯次數」。**那句話描述的是
欄位意圖，不是它實際承重的東西**——`dp/notify/repository.update_template_versioned` 的
docstring 寫明它是**樂觀鎖**：「僅當 DB `VERSION` 等於傳入 version 才成功」。

而那個 📌 在 `a3f9c21e5d84` 成立，是因為該 migration 用 `WHERE "BODY" = :old` **只動出廠列**
——出廠列代表沒有管理者編輯過它，也就不可能有人手上握著該列的表單。本次是無條件 UPDATE，
前提消失：在 migration 之前開著 DP04 編輯表單的管理者，其 `version` 仍與 DB 相符 →
409 `DP_MAIL_004` 衝突檢核**不會觸發** → 他按儲存就把本次的新文案靜默覆寫回舊的。

（今日這條另被 `ensure_renderable` 偶然擋住——它拿新 `VARIABLES` 去驗舊主旨內文，`{doc_name}`
缺 key 而 422。但那只在「佔位名稱有改」時成立，不能當作防線。）

⇒ `SET ... "VERSION" = "VERSION" + 1`，讓既有表單一律撞上版本衝突、看到明確錯誤。
downgrade 同樣**再 +1** 而非還原原值：它是單調遞增的鎖計數，不是要復原的資料。

📌 不動 `CHANNEL`：`EMAIL` 由 `0ac1b791c1a1`（#627）設定，維持不變。
📌 `UPDATED_USER` / `UPDATED_DATE` 亦不動——與 `0ac1b791c1a1`、`a3f9c21e5d84` 一致（模組層級
的既有慣例，非本次決定）。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "7c4e19ab3f52"
down_revision: Union[str, None] = "0d17180b7546"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 與 `b7fa4b6e4fe7` 的 seed 逐字一致（`15e30a8f8b6f` / `0ac1b791c1a1` 只動過 CHANNEL）。
_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

_OLD_SUBJECT = "【催辦】{doc_name} 待簽核已逾 {days} 天"
_OLD_BODY = "{reviewer_name} 您好：\n\n文件「{doc_name}」送審已停留 {days} 天，請儘速至簽核中心處理。" + _FOOTER
_OLD_VARS = "reviewer_name,doc_name,days"

_NEW_SUBJECT = "【催辦】您有 {pending_count} 件送審待簽核"
_NEW_BODY = (
    "{reviewer_name} 您好：\n\n您有 {pending_count} 件送審停留過久，清單如下：\n"
    "{pending_list}\n\n請儘速至簽核中心處理。" + _FOOTER
)
_NEW_VARS = "reviewer_name,pending_count,pending_list"

_SQL = text(
    'UPDATE "DP_NOTIFY_TEMPLATE" '
    'SET "SUBJECT" = :subject, "BODY" = :body, "VARIABLES" = :variables, "VERSION" = "VERSION" + 1 '
    "WHERE \"MODULE\" = 'DM' AND \"TEMPLATE_CODE\" = 'AUTO_REMIND'"
)


def upgrade() -> None:
    op.execute(_SQL.bindparams(subject=_NEW_SUBJECT, body=_NEW_BODY, variables=_NEW_VARS))


def downgrade() -> None:
    """還原為逐筆形狀的出廠文案。

    ⚠️ downgrade 後**程式也必須一起退版**：回滾範本卻留著傳 `pending_*` 的程式碼，
    會讓舊範本的 `{doc_name}` / `{days}` 缺 key 而整批 FAILED——與 upgrade 方向同一個陷阱。
    """
    op.execute(_SQL.bindparams(subject=_OLD_SUBJECT, body=_OLD_BODY, variables=_OLD_VARS))
