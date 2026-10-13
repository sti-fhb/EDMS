"""et_doc_obsoleted_body_draft_wording

Revision ID: a3f9c21e5d84
Revises: 4b1a264bc451
Create Date: 2026-10-13 17:00:00.000000

`DOC_OBSOLETED` 內文「**再次**發布或再開課」改為「發布或再開課」（#231 裁示 Q2 = C）。

## 為何要改

Q2 = C 起，廢止通知**連草稿課程的擁有者一起寄**（改版則不寄——該信寫著「學員開啟
章節時即會看到新內容」，對沒有學員的草稿是假的）。

而廢止信原本寫「上列課程在**再次**發布或再開課時會被擋下」——對一門**從未發布過**的
草稿，那是第一次發布、不是「再次」。新納入的收件人剛好就是會讀到這句的人。

## 🔴 只更新「內文仍是 seed 原文」的那一列

`DOC_OBSOLETED` 為 `MODULE='ET'` 之**管理者可維護**範本（#231 裁示 Q4 = A，可於 DP 後台
編輯主旨 / 內文並啟停）。無條件 UPDATE 會把管理者改過的內容覆寫掉。

故 `WHERE` 多一個 `"BODY" = :old`：只有仍是出廠文字的列會被換掉，動過的保持原樣。
⚠️ 這也表示**管理者若已改過這段，就不會拿到修正後的字**——那是刻意的取捨：
不覆寫使用者的編輯優先於文案一致。

📌 不動 `VERSION`：本次沒有使用者編輯發生，列仍是出廠狀態。

比照 `9b309342e9f3`（DP 範本 VARIABLES 中文化）之做法：依 `TEMPLATE_CODE` 精準 UPDATE、
參數化綁定、downgrade 可逆。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "a3f9c21e5d84"
down_revision: Union[str, None] = "4b1a264bc451"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

_HEAD = (
    "{USER_NAME} 您好：\n\n您課程引用的訓練教材文件已被廢止。\n\n"
    "文件編號：{DOC_ID}\n"
    "文件名稱：{DOC_NAME}\n"
    "受影響課程：{COURSE_LIST}\n\n"
)
_TAIL = "引用，或改引用其他文件。\n課程管理：{COURSE_URL}" + _FOOTER

#: `e8b4c2f17a93` 所 seed 的原文（逐字，供 WHERE 比對）。
_OLD_BODY = _HEAD + "⚠️ 上列課程在**再次發布或再開課**時會因引用已廢止文件而被擋下。請移除該文件的" + _TAIL

#: 修正後：草稿課程是「發布」而非「再次發布」。
_NEW_BODY = _HEAD + "⚠️ 上列課程在**發布或再開課**時會因引用已廢止文件而被擋下。請移除該文件的" + _TAIL

_SQL = text(
    'UPDATE "DP_NOTIFY_TEMPLATE" SET "BODY" = :new '
    'WHERE "MODULE" = \'ET\' AND "TEMPLATE_CODE" = \'DOC_OBSOLETED\' AND "BODY" = :old'
)


def upgrade() -> None:
    op.execute(_SQL.bindparams(new=_NEW_BODY, old=_OLD_BODY))


def downgrade() -> None:
    """還原為 seed 原文——同樣只動「內文仍是本次改後文字」的那一列。"""
    op.execute(_SQL.bindparams(new=_OLD_BODY, old=_NEW_BODY))
