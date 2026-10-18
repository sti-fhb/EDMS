"""et_quiz_retest_body_all_students

Revision ID: d5a7e3c91f48
Revises: b8e2d4f61a37
Create Date: 2026-10-19 10:00:00.000000

`QUIZ_RETEST_REQUIRED` 內文「教師要求**已通過的學員**重新測驗」改為「教師要求重新測驗」（#709）。

## 為何要改

#709 SA 裁示：要求重測的情境是舊題目有問題（出題疏失、內容大改），所有作答過的學員都
拿到同樣的新一輪，不再只限已通過者。新納入的收件人（未通過者）讀到「要求已通過的學員」
會以為信寄錯了。

## 🔴 只更新「內文仍是 seed 原文」的那一列

`QUIZ_RETEST_REQUIRED` 為 `MODULE='ET'` 之**管理者可維護**範本（`IS_SYSTEM=false`），
無條件 UPDATE 會把管理者改過的內容覆寫掉。故 `WHERE` 多一個 `"BODY" = :old`——
⚠️ 管理者若已改過，就不會拿到修正後的字；不覆寫使用者的編輯優先於文案一致。

📌 不動 `VERSION`：本次沒有使用者編輯發生，列仍是出廠狀態。

比照 `a3f9c21e5d84`（`DOC_OBSOLETED` 內文修正）之做法。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "d5a7e3c91f48"
down_revision: Union[str, None] = "b8e2d4f61a37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

_HEAD = "{USER_NAME} 您好：\n\n課程「{COURSE_NAME}」的測驗「{QUIZ_NAME}」內容已更新，"
_TAIL = "您的作答次數已重新計算。\n您先前歷次的作答紀錄與成績完整保留，仍可隨時回看。\n學習連結：{COURSE_URL}" + _FOOTER

#: `a7c31f5e9d24` 所 seed 的原文（逐字，供 WHERE 比對）。
_OLD_BODY = _HEAD + "教師要求已通過的學員重新測驗，" + _TAIL

#: 修正後：對象不限已通過者。
_NEW_BODY = _HEAD + "教師要求重新測驗，" + _TAIL

_SQL = text(
    'UPDATE "DP_NOTIFY_TEMPLATE" SET "BODY" = :new '
    'WHERE "MODULE" = \'ET\' AND "TEMPLATE_CODE" = \'QUIZ_RETEST_REQUIRED\' AND "BODY" = :old'
)


def upgrade() -> None:
    op.execute(_SQL.bindparams(new=_NEW_BODY, old=_OLD_BODY))


def downgrade() -> None:
    """還原為 seed 原文——同樣只動「內文仍是本次改後文字」的那一列。"""
    op.execute(_SQL.bindparams(new=_OLD_BODY, old=_NEW_BODY))
