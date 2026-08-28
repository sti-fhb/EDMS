"""et_survey_question_type_and_delete

Revision ID: 8713c6177f6f
Revises: 1a85b7fe2cff
Create Date: 2026-08-28 16:12:47.400555

課後問卷之題型擴充與刪除支援（#238）。一支 migration 三件事，因為三者互相依存：
沒有題型就不需要 `ANSWER_TEXT`，沒有刪除就不需要改 `UQ_ET_SURVEY_COURSE`。

## 1. `ET_SURVEY_QUESTION.QUESTION_TYPE`

`data-model.md` 原明訂「題型一律**單選**（不設題型欄位）」，2026-08-28 實測回饋要求
新增「問答」題型（教師只填題幹，學員以文字作答），該條因此推翻。值域見
`app/et/constants.py` 之 `ET_SURVEY_QUESTION_TYPE`（`SINGLE` / `TEXT`）。

**`server_default` 加了立刻拿掉**：加是為了讓既有列有值（`NOT NULL` 才立得起來），
拿掉是為了讓應用層必須明確指定題型——留著 DB 預設會讓「忘了傳 `question_type`」
靜默變成單選，而那種錯誤只會在教師發現題目型態不對時才浮現。

## 2. `ET_SURVEY_RESPONSE_D.ANSWER_TEXT` 與 `SO_ID` 改可空

問答題沒有選項可選，故 `SO_ID` 必須放寬為 NULL、另存文字答案。兩者互斥：
單選題填 `SO_ID`、問答題填 `ANSWER_TEXT`（應用層把關，不設 CHECK——比照本專案
DM / DP 之做法，值域一律由應用層負責）。

長度 150 由 #238 明訂。PostgreSQL 的 `VARCHAR(n)` 以**字元**計而非位元組，
中文 150 字可完整容納。

> 學員填寫（`ET-15`）與問卷結果統計（`ET-9`）**尚未實作**，本 migration 是先把模型
> 準備好，兩者的 spec 已於本 issue 同步更新（`spec_us13` / `spec_us9`）。

## 3. `UQ_ET_SURVEY_COURSE` → 部分唯一索引

**本 issue 的必修項，不是選配。** #204 因當時裁示「問卷不可刪除」而未改，並於
`app/et/survey/models.py` 該約束上方留了註解：

> ⚠️ 這是「用不到所以沒壞」，不是「修好了」。日後若開放問卷刪除，此約束會立刻變成
> 缺陷⋯⋯錯誤訊息會是「一門課程僅可建立 1 份」，指向一筆使用者看不見的資料。

#238 開放了「未發布課程可刪除問卷」，那個「日後」就是現在。不改的話教師刪掉問卷後
**永遠建不了新的**，且錯誤訊息完全誤導。

這是本專案第 5 次修同型缺陷（前四次：#202 `ET_CHAPTER`、#203 `ET_ITEM` /
`ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC`、#204 `ET_SURVEY_QUESTION` / `ET_SURVEY_OPTION`）。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8713c6177f6f"
down_revision: Union[str, None] = "1a85b7fe2cff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 問答題答案長度上限（#238 明訂）。PostgreSQL 以字元計，中文 150 字可容。
_ANSWER_TEXT_LEN = 150


def upgrade() -> None:
    # 1. 題型欄位——既有列一律填 SINGLE（本 migration 前問卷只有單選題）
    op.add_column(
        "ET_SURVEY_QUESTION",
        sa.Column("QUESTION_TYPE", sa.String(20), nullable=False, server_default="SINGLE"),
    )
    # 立刻移除 DB 預設：應用層必須明確指定題型，不讓漏傳靜默變成單選
    op.alter_column("ET_SURVEY_QUESTION", "QUESTION_TYPE", server_default=None)

    # 2. 問答題之文字答案；SO_ID 對問答題不適用，放寬為 NULL
    op.add_column(
        "ET_SURVEY_RESPONSE_D",
        sa.Column("ANSWER_TEXT", sa.String(_ANSWER_TEXT_LEN), nullable=True),
    )
    op.alter_column("ET_SURVEY_RESPONSE_D", "SO_ID", existing_type=sa.BigInteger(), nullable=True)

    # 3. 開放刪除問卷 → 全表唯一約束必須改為部分唯一索引
    op.drop_constraint("UQ_ET_SURVEY_COURSE", "ET_SURVEY", type_="unique")
    op.create_index(
        "UX_ET_SURVEY_COURSE",
        "ET_SURVEY",
        ["COURSE_ID"],
        unique=True,
        postgresql_where=sa.text('"DELETED" = 0'),
    )


def downgrade() -> None:
    """還原。

    ⚠️ **第 3 項的還原有時效**：一旦產生「已刪除之問卷與現存問卷同屬一門課程」的資料
    （刪除問卷後再建一份就會），重建全表唯一約束會因重複值而失敗。此為預期行為——
    原約束本就不容許該狀態，需先人工整理再降級。

    ⚠️ 第 2 項還原亦然：若已有問答題之填答（`SO_ID` 為 NULL），`SO_ID` 改回 `NOT NULL`
    會失敗。
    """
    op.drop_index("UX_ET_SURVEY_COURSE", table_name="ET_SURVEY")
    op.create_unique_constraint("UQ_ET_SURVEY_COURSE", "ET_SURVEY", ["COURSE_ID"])

    op.alter_column("ET_SURVEY_RESPONSE_D", "SO_ID", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("ET_SURVEY_RESPONSE_D", "ANSWER_TEXT")

    op.drop_column("ET_SURVEY_QUESTION", "QUESTION_TYPE")
