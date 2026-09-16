"""et_backfill_last_activity_at

Revision ID: ee1d5e46c3ad
Revises: d5a81f37c6b2
Create Date: 2026-09-16 10:52:24.970265

回填 `ET_ENROLLMENT.LAST_ACTIVITY_AT` 之既有資料（#339，#334 的 follow-up）。

異動說明：
- 影響 Table：ET_ENROLLMENT（僅 UPDATE 資料，無 DDL）
- #334 讓該欄涵蓋三種活動（檢視項目 / 提交測驗 / 填答問卷），並依裁示移除了 `tracking`
  內「查詢當下取 `LAST_ACTIVITY_AT` 與 `MAX(SUBMITTED_AT)` 兩者較晚者」的補償查詢。
  移除後該欄只讀欄位本身，而欄位**只有 #334 部署起的新活動才會被寫入**——部署前已提交
  的測驗與問卷，其時間點會從 ET03「最後活動」欄永久消失
- 與前例 `db3214fd6543`（`LAST_ITEM_ID` 明文不回填）不同：那支不回填是因為**資料無從
  得知**，本案資料完整存在且可精確重建（被移除的補償查詢本身就是靠它算的）
- 對正式機為 no-op：日後由 migration 從頭建立、無既有資料

`downgrade` 刻意不實作——回填是覆寫式 UPDATE，舊值（NULL 或更早的時間）已消失，
無從還原。比照 `676114dc0672` 的處理。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee1d5e46c3ad"
down_revision: Union[str, None] = "d5a81f37c6b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 以模組層級常數匯出，供 tests/integration/et/test_et_backfill_last_activity_migration.py
# 直接執行同一份 SQL——測試若重抄一份會 drift，屆時綠燈但實際 migration 是另一套邏輯。
#
# 設計說明：
#
# 1. 不用 `GREATEST`，改以 WHERE 守衛（`IS NULL OR < max_at`）決定要不要寫。
#    一個條件同時達成三件事：既有值較晚時不覆寫、重跑為 no-op、只更新真的會變的列。
#    （附帶更正 #339 body 的一處警告：PostgreSQL 的 `GREATEST` **忽略** NULL 參數，
#    只有全部參數皆 NULL 才回 NULL——「遇 NULL 即回 NULL」是 Oracle / MySQL 的行為。）
#
# 2. `MAX()` 忽略 NULL，故不需另外濾測驗的 `STATUS`。`ET_QUIZ_ATTEMPT_M.SUBMITTED_AT`
#    為 nullable（未交的 attempt），`ET_SURVEY_RESPONSE_M.SUBMITTED_AT` 為 NOT NULL——
#    業務上測驗有「寫到一半」、問卷沒有。兩側不對稱是事實而非疏漏。
#
# 3. 兩側的 `DELETED = 0` **性質不同，不是同一個條件複製兩次**：
#    - 測驗側**吃重**：刪除章節 / 項目 / 課程會經 `EtQuizRepository.soft_delete_cascade`
#      （`quiz/repository.py:312` 的 `.values(**audit)`，audit 含 `deleted=1`）把其下
#      attempt 一併軟刪。對齊 `course/models.py:82`「完課率 / 進度統計務必排除 DELETED = 1」。
#    - 問卷側目前**恆真**、屬防禦性：`soft_delete_survey` 明文不處理填答（刪除僅限草稿
#      課程，草稿無學員故不可能有填答），`soft_delete_question` 同理。兩側差異的理由寫在
#      `survey/repository.py:220-222`：測驗題目可在有作答後刪除，問卷題目不行。
#
# 4. `ET_SURVEY` 的 JOIN **純粹用於解析 `COURSE_ID`**（`ET_SURVEY_RESPONSE_M` 沒有該欄），
#    不參與有效性判斷，故不濾 `ET_SURVEY.DELETED`——有效性由活動列自身的 `DELETED` 決定。
#
# 5. 不濾 `ET_ENROLLMENT.IS_REMOVED`：本支修的是「欄位值與事實不符」，不是決定誰要顯示。
#    可見性歸查詢層（`tracking/repository.build_student_list_stmt()` 已帶
#    `is_removed.is_(False)`），欄位值歸事實。
BACKFILL_SQL = """
UPDATE "ET_ENROLLMENT" AS e
SET "LAST_ACTIVITY_AT" = act.max_at
FROM (
    SELECT "USER_ID", "COURSE_ID", MAX("SUBMITTED_AT") AS max_at
    FROM (
        SELECT a."USER_ID", a."COURSE_ID", a."SUBMITTED_AT"
        FROM "ET_QUIZ_ATTEMPT_M" a
        WHERE a."DELETED" = 0
        UNION ALL
        SELECT r."USER_ID", s."COURSE_ID", r."SUBMITTED_AT"
        FROM "ET_SURVEY_RESPONSE_M" r
        JOIN "ET_SURVEY" s ON s."SURVEY_ID" = r."SURVEY_ID"
        WHERE r."DELETED" = 0
    ) u
    GROUP BY "USER_ID", "COURSE_ID"
) AS act
WHERE e."USER_ID" = act."USER_ID"
  AND e."COURSE_ID" = act."COURSE_ID"
  AND act.max_at IS NOT NULL
  AND (e."LAST_ACTIVITY_AT" IS NULL OR e."LAST_ACTIVITY_AT" < act.max_at)
"""


def upgrade() -> None:
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    # 刻意不實作：回填為覆寫式 UPDATE，舊值已消失，假還原只會寫入錯誤資料。
    pass
