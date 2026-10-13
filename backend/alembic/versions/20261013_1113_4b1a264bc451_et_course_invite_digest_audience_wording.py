"""et course invite digest audience wording (#605)

Revision ID: 4b1a264bc451
Revises: e8b4c2f17a93
Create Date: 2026-10-13 11:13:07.962390

課程邀請彙整通知（`COURSE_INVITE_DIGEST`）內文之「受訓單位標籤」改為「受訓對象」，
與 #538 / PR #552 的改名一致（學員被補加入課程時收到的 Email）。

異動說明：
- 影響 Table：DP_NOTIFY_TEMPLATE（更新 1 列之 BODY 與 VERSION，不新增 / 不刪除列）
- 變數 `{USER_NAME}` `{COURSE_LIST}` 不動（#534 之佔位檢核只在 DP04 儲存時執行，
  migration 直寫 DB 不經過它，故本檔自行保持變數不變）

⚠️ **只在內文仍等於原種子值時更新**：管理者可能已於 DP04 改過這個範本，覆蓋會讓其修改
無聲消失。條件不成立時本 migration 不做任何事，屬預期。downgrade 對稱：只在內文仍等於
本次新值時還原。

`VERSION + 1`：VERSION 是 DP04 編輯的樂觀鎖。不遞增的話，管理者若在 migration 前開著
編輯畫面，之後按儲存會以同一版號通過檢查，把本次更新蓋回舊內文且不報錯。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "4b1a264bc451"
down_revision: Union[str, None] = "e8b4c2f17a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 與種子（`c4e8f1a6d372`）相同的頁尾；逐字一致才比對得到。
_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
_OLD_BODY = "{USER_NAME} 您好：\n\n因受訓單位標籤異動，您已被加入下列課程：\n\n{COURSE_LIST}" + _FOOTER
_NEW_BODY = "{USER_NAME} 您好：\n\n因受訓對象異動，您已被加入下列課程：\n\n{COURSE_LIST}" + _FOOTER


def _replace_body(from_body: str, to_body: str) -> None:
    """內文等於 `from_body` 時才改為 `to_body` 並遞增 VERSION；否則不動。"""
    op.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "BODY" = :to_body, "VERSION" = "VERSION" + 1 '
            'WHERE "MODULE" = \'ET\' AND "TEMPLATE_CODE" = \'COURSE_INVITE_DIGEST\' AND "BODY" = :from_body'
        ).bindparams(to_body=to_body, from_body=from_body)
    )


def upgrade() -> None:
    _replace_body(_OLD_BODY, _NEW_BODY)


def downgrade() -> None:
    _replace_body(_NEW_BODY, _OLD_BODY)
