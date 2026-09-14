"""ET03 學員學習狀況追蹤之查詢（US9 / #322）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶 `DELETED = 0`。

## 本檔的聚合全部是「一門課程 × 多位學員」

`progress/repository.completion_counts_by_course()` 是**相反的形狀**（一位學員 × 多門
課程，ET04「我的課程」用）。兩者不能互相取代，但**防禦必須一致**——見
`completion_counts_by_student()` 的 docstring。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.users.models import DpUser  # 唯讀 join（已列於 et/spec.md §外模組 table 引用清單）
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuizAttemptM


class EtTrackingRepository:
    """教師端之學員學習狀況查詢。"""

    def build_student_list_stmt(self, *, course_id: int):
        """該課程之**未移除**學員（供 `paginate()`）。

        `IS_REMOVED` 與 `DELETED` **語意不同、兩個都要濾**：前者是教師主動移除（學習
        歷史保留、不計入完課率分母），後者是資料層軟刪。只濾其一會讓被移除的學員重新
        出現在教師的清單上，而 AC 5 明訂他不該出現。
        """
        return (
            select(EtEnrollment)
            .where(
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
            .order_by(EtEnrollment.joined_at.asc(), EtEnrollment.enrollment_id.asc())
        )

    async def completion_counts_by_student(
        self, db: AsyncSession, *, course_id: int, user_ids: list[str]
    ) -> dict[str, tuple[int, int]]:
        """`{user_id: (完成項目數, 總項目數)}`——進度百分比與完課判定的共同來源。

        ## 與 `progress.completion_counts_by_course()` 的關係

        那支是「一位學員 × 多門課程」，本支是「**一門課程 × 多位學員**」。形狀相反、
        不能互相取代，但**兩個防禦必須一致**：

        1. ⚠️ **完成數必須 JOIN 回 `ET_ITEM` / `ET_CHAPTER` 過濾軟刪除**。`ET_PROGRESS`
           的列在項目被刪除後仍然留著（那是學習歷史，刻意不連帶刪），若直接 `count(*)`
           會拿分母已縮小、分子沒縮小的兩個數字相除——**教師刪掉一個項目就會讓學員的
           進度變成 200%**。
        2. 課程層以 `ET_CHAPTER.COURSE_ID` 推導而非 `ET_PROGRESS.COURSE_ID`：後者是寫入
           當下存下的冗餘欄位，前者才是當前的結構事實。

        **總項目數對全班相同**，故只查一次、不進 `GROUP BY`。

        ⚠️ 完成數與平均成績**刻意分兩支查詢**：兩個一對多關聯併進同一個 `GROUP BY` 會
        互相灌大彼此的計數（2 項目 × 3 次作答 → 兩個數字都變 6）。
        """
        total = await db.scalar(
            select(func.count(EtItem.item_id))
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtChapter.course_id == course_id, EtItem.deleted == 0, EtChapter.deleted == 0)
        )
        total = total or 0
        if not user_ids:
            return {}

        done_rows = await db.execute(
            select(EtProgress.user_id, func.count(EtProgress.progress_id))
            .select_from(EtProgress)
            .join(EtItem, EtItem.item_id == EtProgress.item_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtProgress.user_id.in_(user_ids),
                EtChapter.course_id == course_id,
                EtProgress.is_completed.is_(True),
                EtProgress.deleted == 0,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
            .group_by(EtProgress.user_id)
        )
        done_by_user = dict(done_rows.all())
        return {user_id: (done_by_user.get(user_id, 0), total) for user_id in user_ids}

    async def avg_best_score_by_student(
        self, db: AsyncSession, *, course_id: int, user_ids: list[str]
    ) -> dict[str, float]:
        """`{user_id: 已作答測驗之最高分平均}`——**未作答者不在回傳的 key 裡**。

        ## 分母是「該學員作答過的測驗數」，不是課程的測驗總數

        `FR-ET-US9-03`「以學員**已作答測驗**之最高分平均計算（未作答測驗排除）」。
        課程有兩個測驗而學員只考了一個時，兩種分母會給出差一倍的數字。

        ## 兩層聚合

        內層先取每位學員在**每個測驗**的最高分（重考多次取最好的一次），外層再對測驗
        取平均。一次算完會變成「所有 attempt 的平均」——重考愈多次分數被拉得愈低，與
        `FR-ET-US6-10`「以最高分為結業成績」矛盾。

        只計**已提交**（`SUBMITTED_AT` 非空且 `SCORE` 非空）的 attempt：作答中的那筆
        還沒有分數，計入會讓平均無故下降。
        """
        if not user_ids:
            return {}
        best_per_quiz = (
            select(
                EtQuizAttemptM.user_id.label("user_id"),
                EtQuizAttemptM.quiz_id.label("quiz_id"),
                func.max(EtQuizAttemptM.score).label("best"),
            )
            .where(
                EtQuizAttemptM.user_id.in_(user_ids),
                EtQuizAttemptM.course_id == course_id,
                EtQuizAttemptM.score.is_not(None),
                EtQuizAttemptM.deleted == 0,
            )
            .group_by(EtQuizAttemptM.user_id, EtQuizAttemptM.quiz_id)
            .subquery()
        )
        rows = await db.execute(
            select(best_per_quiz.c.user_id, func.avg(best_per_quiz.c.best)).group_by(best_per_quiz.c.user_id)
        )
        return {user_id: float(avg) for user_id, avg in rows.all()}

    async def last_submitted_at_by_student(
        self, db: AsyncSession, *, course_id: int, user_ids: list[str]
    ) -> dict[str, object]:
        """`{user_id: 最後一次測驗提交時間}`。

        ⚠️ **`ET_ENROLLMENT.LAST_ACTIVITY_AT` 不含測驗提交**——它只在
        `progress/repository.set_last_item()`（檢視項目）被更新，而 `data-model`
        §ET_ENROLLMENT 定義該欄位是「最近一次學習動作 / **測驗提交**時間」。

        學員開著測驗寫 30 分鐘再提交時，那個欄位會停在進入測驗的時間。本支補上缺的那
        一半，由 service 取兩者較晚者。

        > 在查詢層補齊而非去修 `attempt/`：本 issue 不該擴張到別的模組的寫入路徑；
        > `attempt` 提交時不更新該欄位這個落差另列 follow-up。
        """
        if not user_ids:
            return {}
        rows = await db.execute(
            select(EtQuizAttemptM.user_id, func.max(EtQuizAttemptM.submitted_at))
            .where(
                EtQuizAttemptM.user_id.in_(user_ids),
                EtQuizAttemptM.course_id == course_id,
                EtQuizAttemptM.submitted_at.is_not(None),
                EtQuizAttemptM.deleted == 0,
            )
            .group_by(EtQuizAttemptM.user_id)
        )
        return {user_id: submitted for user_id, submitted in rows.all()}

    async def user_names(self, db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
        """`{user_id: user_name}`——**一次查回整頁**，不逐筆。

        唯讀查詢 `DP_USER`，屬 `spec.md` §外模組 table 引用清單之既有例外（US9 已列）。
        濾 `deleted == 0`：帳號已刪者回 `None`，前端顯示「—」。
        """
        if not user_ids:
            return {}
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name).where(DpUser.user_id.in_(user_ids), DpUser.deleted == 0)
        )
        return {user_id: name for user_id, name in rows.all()}

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        """取課程（未刪除）——供擁有權與「視同關閉」判定。"""
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))
