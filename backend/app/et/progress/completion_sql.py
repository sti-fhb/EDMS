"""完課判定的 **SQL 版**（#464）——「已完課的 (課程, 學員) 對」之共用片段。

## 這是 `enrollment/rules.is_course_completed(done, total)` 的同義實作

Python 版吃單一學員的計數，供逐筆判斷；本片段把同一條規則下推到 SQL，供「多學員 ×
多課程」的查詢與寫入使用。**兩者必須對同一組事實給出相同答案**——
`tests/integration/et/test_et_completion_sql.py::TestAgreesWithPythonRule` 釘住這件事，
兩邊的規則若要改，必須一起改。

規則：**該課程所有未刪除項目皆已完成，且至少有一個項目**（`total > 0 AND done >= total`）。

## 消費者

| 消費者 | 用途 |
|---|---|
| `approval/query_repository` | ET04 查詢中「不需核可課程完課即通過」那一側 |
| `progress/repository.stamp_completed_at` | 第一次完課時寫入 `ET_ENROLLMENT.COMPLETED_AT` |

⚠️ **第三份同義實作**：`app/et/stats/repository.py`（#466 儀表板）另有一份以
`case((and_(totals.c.total > 0, done_col >= totals.c.total), 1), else_=0)` 寫成的版本，
**未改用本片段**——那是 #466 剛合併、屬別人的區域，本次不順手重構。日後統一時注意：
那份的 `dones` 以 `EtProgress.course_id` 分組（見下方第 2 點），本片段不是。

## 兩道防禦（與 `tracking/repository.completion_counts_by_student` 一致）

1. **完成數 JOIN 回 `ET_ITEM` / `ET_CHAPTER` 並濾軟刪除。** 正常路徑下
   `EtItemRepository.soft_delete_with_cascade` 會一併軟刪 `ET_PROGRESS`，所以只濾
   `EtProgress.deleted == 0` 今天就夠——但 JOIN 回去讓「cascade 若被改壞」時的結果是
   **少算**而不是多算（分子分母同源）。
2. **課程層以 `ET_CHAPTER.COURSE_ID` 推導**，不用 `ET_PROGRESS.COURSE_ID`——後者是寫入
   當下存下的冗餘欄位，前者才是當前的結構事實。

⚠️ **兩個聚合各自成一支子查詢**，不併進同一個 `GROUP BY`——兩個一對多關聯放在一起會互相
灌大彼此的計數。
"""

from sqlalchemy import Subquery, func, select

from app.et.course.models import EtChapter, EtItem
from app.et.progress.models import EtProgress


def completed_pairs(*, course_id: int | None = None, user_ids: list[str] | None = None) -> Subquery:
    """已完課的 `(course_id, user_id)` 對。

    Args:
        course_id: 限定單一課程；`None` 表不限。寫入端一律帶它（只算受影響的那門課）。
        user_ids: 限定學員；`None` 表不限。

    Returns:
        欄位為 `course_id`、`user_id` 的子查詢。⚠️ **不含選課條件**（在籍 / 已移除）——
        那是消費者各自的決定，見 `approval/query_repository` 與
        `progress/repository.stamp_completed_at` 的說明。
    """
    totals = (
        select(EtChapter.course_id.label("course_id"), func.count(EtItem.item_id).label("total"))
        .select_from(EtItem)
        .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
        .where(EtItem.deleted == 0, EtChapter.deleted == 0)
        .group_by(EtChapter.course_id)
    )
    dones = (
        select(
            EtChapter.course_id.label("course_id"),
            EtProgress.user_id.label("user_id"),
            func.count(EtProgress.progress_id).label("done"),
        )
        .select_from(EtProgress)
        .join(EtItem, EtItem.item_id == EtProgress.item_id)
        .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
        .where(
            EtProgress.is_completed.is_(True),
            EtProgress.deleted == 0,
            EtItem.deleted == 0,
            EtChapter.deleted == 0,
        )
        .group_by(EtChapter.course_id, EtProgress.user_id)
    )
    if course_id is not None:
        totals = totals.where(EtChapter.course_id == course_id)
        dones = dones.where(EtChapter.course_id == course_id)
    if user_ids is not None:
        dones = dones.where(EtProgress.user_id.in_(user_ids))

    t = totals.subquery("completion_totals")
    d = dones.subquery("completion_dones")
    return (
        select(d.c.course_id, d.c.user_id)
        .join(t, t.c.course_id == d.c.course_id)
        # ⚠️ **`total > 0` 今天是 no-op，別誤以為它是那道防線。** 擋下「沒有任何項目的
        # 課程」的是**內連接**：`totals` 從 `EtItem` 出發 `GROUP BY`，零項目的課程根本不會
        # 產生那一組，`total` 結構上不可能是 0。2026-09-30 變異檢查實測：拿掉它，全綠。
        #
        # ⭐ 保留它是為了**日後**：若有人把 `totals` 改成從 `EtCourse` LEFT JOIN（例如為了
        # 列出零項目課程），`total` 就會出現 0，而沒有這道守門的話，那些課程的每位學員
        # 會因 vacuous truth（`0 >= 0`）被列為「通過」。它守的是未來，不是現在。
        # Python 版的同一條規則見 `enrollment/rules.is_course_completed`。
        .where(t.c.total > 0, d.c.done >= t.c.total)
        .subquery("completed_pairs")
    )
