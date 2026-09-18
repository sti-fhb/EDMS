"""et drop invitation (#362)

Revision ID: f1d93a5c7b04
Revises: 6e65f03ce681
Create Date: 2026-09-18 10:30:00.000000

移除 `ET_INVITATION`：Email 邀請不再有「待加入」中間狀態，教師按下寄出的當下就寫
`ET_ENROLLMENT`（見 `app/et/invitation/service.py` 模組 docstring 的取捨表）。

異動說明：
- 影響 Table：`ET_INVITATION`（整張移除）、`ET_ENROLLMENT`（補入尚未加入者）
- ET 模組建表數 29 → 28

## `PENDING` 的邀請要補成 `ET_ENROLLMENT`，不能直接丟掉

那些是教師**已經按下寄出**的邀請。在新語意下同一個動作就是「加入」，所以直接刪表
等於默默取消教師已經做過的事——受邀者收過信、以為自己在課程裡，清單上卻沒有他。

`JOINED_AT` 取該筆邀請的 `SENT_AT`（教師按下寄出的時點），不取 migration 執行時間：
後者會讓所有回填的人看起來是同一秒加入的，且晚於他們實際收到信的日子。

**`JOINED` / `REVOKED` 不回填**：前者的 `ET_ENROLLMENT` 在 accept 當下已建立；後者是
教師明示不要那個人。

## 🔴 撞到既有列時 `DO NOTHING`，**不**把被移除的學員救回來

`UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一，被移除者那一列仍在。改用 `DO UPDATE`
（等同執行期 `upsert_enrollment` 的行為）在這裡是錯的方向：`ET_INVITATION` 沒有記
「移除發生在邀請之前還是之後」，而兩種順序要的結果相反——

| 實際順序 | `DO UPDATE` | `DO NOTHING` |
|---|---|---|
| 先移除、後邀請 | ✅ 正確帶回 | ⚠️ 沒帶回，教師需重按一次邀請 |
| 先邀請、後移除 | 🔴 **靜默恢復存取權**，教師不會知道 | ✅ 維持移除 |

兩種錯法的代價不對稱：`DO NOTHING` 的錯由教師一次點擊修好（現在邀請即加入，立刻
生效）；`DO UPDATE` 的錯是把已被移除的人放回課程且**無人會發現**。

## 為何 SELECT 帶 `ORDER BY "SENT_AT"`

`ET_INVITATION` **沒有** (COURSE_ID, EMAIL) 唯一約束（`checklists/requirements.md` 早已
記過這個缺口），所以同一人同一課可能有多列 `PENDING`。

`ON CONFLICT DO NOTHING` 本身擋得住同一句 INSERT 內的重複——實測 2 列來源只插入 1 列
（`DO UPDATE` 才會拋 "cannot affect row a second time"）。但**留下哪一列沒有保證**，
於是 `JOINED_AT` 會是那幾次邀請中任意一次的 `SENT_AT`。加上排序後固定取**最早**那次，
也就是「教師第一次邀請他」的時點，與單筆情形的語意一致。

## 查無帳號的 Email 一併落空

SA 裁示「只邀請既有帳號」是後來才加的檢核，早期可能留有寄給非 EDMS 帳號的 `PENDING`
列。它們無 `USER_ID` 可對應，JOIN 不到即自然略過——那些人本來也就進不了系統。

## 回滾

`downgrade()` 重建**空表**。原始邀請列（含 token 雜湊與寄送時點）無法還原，回填進
`ET_ENROLLMENT` 的那些人也不會被移除——回滾只恢復結構，不恢復資料。

實務上不需要還原：token 的唯一用途是已刪除的 accept 端點，重建的列也沒有任何程式會讀。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "f1d93a5c7b04"
down_revision: Union[str, Sequence[str], None] = "6e65f03ce681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 回填列的 `JOIN_SOURCE`——與執行期 `upsert_enrollment` 寫的值相同，
#: 使回填進來的人在學員清單上與日後受邀者無從區別（他們的來源確實相同）。
_SOURCE_EMAIL_INVITE = "EMAIL_INVITE"

#: `COMPLETION_STATUS` 為 NOT NULL 但實際上是死欄位（全系統只寫得出 `NOT_STARTED`，
#: 完課與否一律即時計算）。此處沿用同一個值，不代表這些人真的「未開始」。
_COMPLETION_NOT_STARTED = "NOT_STARTED"

_BACKFILL = text(
    """
    INSERT INTO "ET_ENROLLMENT" (
        "USER_ID", "COURSE_ID", "JOIN_SOURCE", "JOINED_AT", "COMPLETION_STATUS",
        "IS_REMOVED", "CREATED_USER", "CREATED_DATE", "DELETED"
    )
    SELECT u."USER_ID", i."COURSE_ID", :source, i."SENT_AT", :completion,
           false, 'SYSTEM', i."SENT_AT", 0
    FROM "ET_INVITATION" i
    JOIN "DP_USER" u ON lower(u."EMAIL") = lower(i."EMAIL")
    WHERE i."STATUS" = 'PENDING' AND i."DELETED" = 0
    ORDER BY i."SENT_AT"
    ON CONFLICT ON CONSTRAINT "UQ_ET_ENROLLMENT_USER_COURSE" DO NOTHING
    """
)


def upgrade() -> None:
    op.execute(_BACKFILL.bindparams(source=_SOURCE_EMAIL_INVITE, completion=_COMPLETION_NOT_STARTED))
    op.drop_index("IX_ET_INVITATION_COURSE", table_name="ET_INVITATION")
    op.drop_table("ET_INVITATION")


def downgrade() -> None:
    op.create_table(
        "ET_INVITATION",
        sa.Column("INVITATION_ID", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("COURSE_ID", sa.BigInteger(), nullable=False),
        sa.Column("EMAIL", sa.String(length=255), nullable=False),
        sa.Column("TOKEN_HASH", sa.String(length=64), nullable=False),
        sa.Column("STATUS", sa.String(length=20), nullable=False),
        sa.Column("SENT_AT", sa.DateTime(timezone=True), nullable=False),
        sa.Column("LAST_SENT_AT", sa.DateTime(timezone=True), nullable=False),
        sa.Column("JOINED_AT", sa.DateTime(timezone=True), nullable=True),
        sa.Column("REVOKED_AT", sa.DateTime(timezone=True), nullable=True),
        sa.Column("SEND_STATUS_CODE", sa.String(length=20), nullable=True),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("DELETED", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["COURSE_ID"], ["ET_COURSE.COURSE_ID"], name="FK_ET_INVITATION_COURSE"),
        sa.PrimaryKeyConstraint("INVITATION_ID", name="PK_ET_INVITATION"),
        sa.UniqueConstraint("TOKEN_HASH", name="UQ_ET_INVITATION_TOKEN_HASH"),
    )
    op.create_index("IX_ET_INVITATION_COURSE", "ET_INVITATION", ["COURSE_ID"], unique=False)
