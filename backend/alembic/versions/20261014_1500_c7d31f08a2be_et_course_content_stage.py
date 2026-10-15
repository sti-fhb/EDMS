"""et_course_content_stage

Revision ID: c7d31f08a2be
Revises: b4e7c91d2a36
Create Date: 2026-10-14 15:00:00.000000

已發布課程的編輯改為暫存、按「更新」跑發布檢核後才一起生效（#631）。

異動說明：
- 新增 Table `ET_COURSE_CONTENT_STAGE`：已發布課程的編輯暫存區，存「即將生效的
  完整內容樹」。套用時以 `SOURCE_ID` 與活表對帳

## 為何不動既有的 11 張內容表

活表（`ET_CHAPTER` / `ET_ITEM` / `ET_MATERIAL` / `ET_MATERIAL_VIDEO` /
`ET_MATERIAL_DOC` / `ET_QUIZ` / `ET_QUESTION` / `ET_OPTION` / `ET_SURVEY` /
`ET_SURVEY_QUESTION` / `ET_SURVEY_OPTION`）**始終是已生效版本**。

另一個方向（活表存編輯中版本、學員端改讀快照）要稽核學員／統計側約 308 處讀取，而
漏改一處的症狀是**學員看到尚未更新的內容**——畫面正常、沒有錯誤、測試不一定覆蓋得到。
本方向把新增的儲存體放在沒有人讀的那一側，漏改的症狀退化為「某個編輯立刻生效」，
也就是今天的行為，看得見。

量測見 #631 規劃留言：11 張內容表、約 308 處學員側引用、7 條學員資料 → 內容表的硬
外鍵（`ET_PROGRESS.ITEM_ID`、`ET_QUIZ_ATTEMPT_D.QUESTION_ID` 等）。那 7 條**不得斷線**
——本表不換活表的 id，內容列的建立與刪除只發生在「更新」當下。

## `SOURCE_ID` 刻意不設外鍵

它指向 11 張不同的表，型別由同列的 `ENTITY_TYPE` 決定，無法以單一 FK 表達。

## `PARENT_STAGE_ID` 自參照

巢狀新增（新章節 → 新項目 → 新測驗 → 新題目 → 新選項）在套用前都沒有活表 id。
自參照讓暫存列用自己的 PK 互相指，不需要暫時鍵與事後映射。

## `PAYLOAD` 用 TEXT 而非 JSONB

比照 `DP_AUDIT_LOG.BEFORE_VALUE`：專案型別限用集合不含 JSONB（`docs/specs/dp/research.md`
§6，DM 亦同此裁定）。本表也不做 JSON 條件查詢——一律以 `COURSE_ID` 整棵載入後在
Python 重建。

## 兩個部分索引

- `UX_..._SOURCE`：一個活表列在同一課程的暫存區只能有一份對應。⚠️ 條件含 `DELETED = 0`
  ——全表唯一會讓「清空暫存 → 再次編輯」永久失敗（已軟刪的列仍佔住鍵），與
  `ET_MATERIAL_DOC` / `ET_ITEM` 踩過的是同一個坑
- `IX_..._COURSE`：載入一律是「某課程的整棵樹」，這是唯一的查詢形狀

⛔ 本表**不回填**：執行當下沒有任何課程處於編輯中，暫存區按定義是空的。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "c7d31f08a2be"
down_revision: str | None = "b4e7c91d2a36"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "ET_COURSE_CONTENT_STAGE"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("STAGE_ID", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("COURSE_ID", sa.BigInteger(), nullable=False),
        sa.Column("ENTITY_TYPE", sa.String(length=20), nullable=False),
        sa.Column("SOURCE_ID", sa.BigInteger(), nullable=True),
        sa.Column("PARENT_STAGE_ID", sa.BigInteger(), nullable=True),
        sa.Column("SORT_ORDER", sa.Integer(), nullable=False),
        sa.Column("PAYLOAD", sa.Text(), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("DELETED", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("STAGE_ID", name="PK_ET_COURSE_CONTENT_STAGE"),
        sa.ForeignKeyConstraint(["COURSE_ID"], ["ET_COURSE.COURSE_ID"], name="FK_ET_COURSE_CONTENT_STAGE_COURSE"),
        sa.ForeignKeyConstraint(
            ["PARENT_STAGE_ID"],
            [f"{_TABLE}.STAGE_ID"],
            name="FK_ET_COURSE_CONTENT_STAGE_PARENT",
        ),
    )
    op.create_index(
        "UX_ET_COURSE_CONTENT_STAGE_SOURCE",
        _TABLE,
        ["COURSE_ID", "ENTITY_TYPE", "SOURCE_ID"],
        unique=True,
        postgresql_where=sa.text('"DELETED" = 0 AND "SOURCE_ID" IS NOT NULL'),
    )
    op.create_index("IX_ET_COURSE_CONTENT_STAGE_COURSE", _TABLE, ["COURSE_ID", "DELETED"])


def downgrade() -> None:
    op.drop_index("IX_ET_COURSE_CONTENT_STAGE_COURSE", table_name=_TABLE)
    op.drop_index("UX_ET_COURSE_CONTENT_STAGE_SOURCE", table_name=_TABLE)
    op.drop_table(_TABLE)
