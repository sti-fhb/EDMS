"""ET03 學員學習狀況追蹤之查詢（US9 / #322）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶 `DELETED = 0`。

## 本檔的聚合全部是「一門課程 × 多位學員」

`progress/repository.completion_counts_by_course()` 是**相反的形狀**（一位學員 × 多門
課程，ET04「我的課程」用）。兩者不能互相取代，但**防禦必須一致**——見
`completion_counts_by_student()` 的 docstring。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.users.models import DpUser  # 唯讀 join（已列於 et/spec.md §外模組 table 引用清單）
from app.et.constants import ATTEMPT_IN_PROGRESS, GRADED_STATUSES
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuiz, EtQuizAttemptM, EtQuizRetryReset
from app.et.survey.models import (
    EtSurvey,
    EtSurveyOption,
    EtSurveyQuestion,
    EtSurveyResponseD,
    EtSurveyResponseM,
)


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

    async def in_progress_attempt_user_ids(self, db: AsyncSession, *, course_id: int, user_ids: list[str]) -> set[str]:
        """本課程中**有作答中（未提交）attempt** 的學員集合（`ET-MSG-ET03-003`）。

        ## 為何逐人判定，不做課程層級的存在性判斷

        「這門課有人在作答」與「**這位**學員在作答」是兩回事。用前者會讓全班每一列
        都跳出警告，警告出現在不需要的地方就會被當成雜訊略過——真正該停下來看的那次
        也一起被略過。

        ## 與 `completion_status` 的 `IN_PROGRESS` 無關

        那個值是**課程學習**進行中（由完成項目數導出），與有沒有正在寫的考卷無關。
        兩者同名不同義，正是本欄位補得這麼晚的原因。

        回 `set` 而非 `dict`：呼叫端只問有無，回 bool 的 dict 會讓 `.get()` 的預設值
        變成另一個要想的問題。
        """
        if not user_ids:
            return set()
        rows = await db.execute(
            select(EtQuizAttemptM.user_id)
            .where(
                EtQuizAttemptM.user_id.in_(user_ids),
                EtQuizAttemptM.course_id == course_id,
                EtQuizAttemptM.status == ATTEMPT_IN_PROGRESS,
                EtQuizAttemptM.deleted == 0,
            )
            .distinct()
        )
        return {user_id for (user_id,) in rows.all()}

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

    async def quizzes_of_course(self, db: AsyncSession, course_id: int) -> list[EtQuiz]:
        """該課程之所有測驗（依章節與項目順序）。

        來源是 `ET_ITEM` 而非 `ET_QUIZ` 自身——測驗是掛在章節項目下的，未掛載的孤兒
        測驗不屬於任何課程。JOIN 鏈同時濾三層軟刪除：章節、項目、測驗。
        """
        rows = await db.execute(
            select(EtQuiz)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .join(EtQuiz, EtQuiz.quiz_id == EtItem.quiz_id)
            .where(
                EtChapter.course_id == course_id,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
                EtQuiz.deleted == 0,
            )
            .order_by(EtChapter.sort_order.asc(), EtItem.sort_order.asc())
        )
        return list(rows.scalars().all())

    async def attempts_of_course(self, db: AsyncSession, course_id: int) -> list[EtQuizAttemptM]:
        """該課程之**所有已閱卷** attempt（全班、全測驗，一次取回）。

        區塊 2 要「一次列出所有曾作答之學員」，逐學員查就是 N+1。一門課的 attempt
        量級是「學員數 × 測驗數 × 重考次數」，仍遠小於分頁的必要門檻。

        **只取已閱卷**（`GRADED_STATUSES`）：進行中的還沒有成績，列出來是一列空白。
        與學員端 `attempt/repository.list_attempts` 同一組白名單。
        """
        rows = await db.execute(
            select(EtQuizAttemptM)
            .where(
                EtQuizAttemptM.course_id == course_id,
                EtQuizAttemptM.status.in_(GRADED_STATUSES),
                EtQuizAttemptM.deleted == 0,
            )
            .order_by(EtQuizAttemptM.user_id.asc(), EtQuizAttemptM.quiz_id.asc(), EtQuizAttemptM.attempt_no.asc())
        )
        return list(rows.scalars().all())

    async def reset_bases_of_course(self, db: AsyncSession, course_id: int) -> dict[tuple[str, int], int]:
        """`{(user_id, quiz_id): 重置基準}`——一次取全班。

        基準為 `MAX(ATTEMPT_COUNT_AT_RESET)`，與 `attempt/repository.reset_base()` 同
        定義（那支是單一學員單一測驗，此處為整門課批次）。無重置紀錄者不在 key 裡，
        呼叫端視為 0。

        """
        quiz_ids = (
            select(EtItem.quiz_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtChapter.course_id == course_id,
                EtItem.quiz_id.is_not(None),
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
        )
        rows = await db.execute(
            select(
                EtQuizRetryReset.user_id,
                EtQuizRetryReset.quiz_id,
                func.max(EtQuizRetryReset.attempt_count_at_reset),
            )
            # ⚠️ **以 `QUIZ_ID` 過濾，不以 `COURSE_ID`**——基準的口徑必須與
            # `attempt/repository.reset_base()`（作答流程實際採用的那支）**逐字一致**。
            # 本表雖有 `COURSE_ID`，但那支只認 `(USER_ID, QUIZ_ID)`；此處若多帶課程條件，
            # 同一個測驗掛在兩門課時兩邊會算出不同的基準，表現為「按鈕可點、按下去 409」
            # （或反之）。
            #
            # **append-only**（`AuditLogBaseModel`，只有 `CREATED_*`），**沒有 `DELETED`
            # 欄位**——它是已用次數的計算基準，能被軟刪除就等於能讓配額憑空回復而查不到
            # 是誰做的。
            .where(EtQuizRetryReset.quiz_id.in_(quiz_ids))
            .group_by(EtQuizRetryReset.user_id, EtQuizRetryReset.quiz_id)
        )
        return {(user_id, quiz_id): base for user_id, quiz_id, base in rows.all()}

    async def get_attempt_with_course(self, db: AsyncSession, attempt_id: int):
        """取 attempt 與其課程——**教師端授權以課程擁有者判定**。

        ⚠️ 與學員端 `attempt/service._require_own_attempt` 的判定**不同**：那支比對
        `USER_ID`（只能看自己的考卷），教師要看的正是別人的。但**不可放寬成「任何教師
        都能看」**——那等於全站考卷對所有教師公開，故改以「該 attempt 所屬課程的
        `OWNER_ID` == 操作者」判定。

        用 `ATTEMPT.COURSE_ID`（提交當下的快照欄位）而非現查反查鏈：章節被刪或項目被
        移動時反查會斷，而那時考卷仍該看得到。
        """
        rows = await db.execute(
            select(EtQuizAttemptM, EtCourse)
            .join(EtCourse, EtCourse.course_id == EtQuizAttemptM.course_id)
            .where(
                EtQuizAttemptM.attempt_id == attempt_id,
                # 只給已閱卷的——`IN_PROGRESS` 那筆還沒有成績，回出去的是學員正在寫的
                # 答案而非考卷。學員端 `/result` 同一組白名單。
                EtQuizAttemptM.status.in_(GRADED_STATUSES),
                EtQuizAttemptM.deleted == 0,
                EtCourse.deleted == 0,
            )
        )
        return rows.first()

    async def get_enrollment(self, db: AsyncSession, *, course_id: int, user_id: str) -> EtEnrollment | None:
        """該學員於該課程之**未移除** enrollment。

        已移除者回 `None`（由呼叫端轉 404）——重複移除不是「無害的冪等」，它代表教師
        看到的清單已經過期，靜默成功會讓他以為剛才那一下有效。
        """
        return await db.scalar(
            select(EtEnrollment).where(
                EtEnrollment.course_id == course_id,
                EtEnrollment.user_id == user_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )

    async def get_quiz_in_course(self, db: AsyncSession, *, course_id: int, quiz_id: int) -> EtQuiz | None:
        """該測驗是否屬於該課程——**防止跨課程操作**。

        沒有這道檢查的話，教師可以拿自己課程的 `course_id` 配上別人課程的 `quiz_id`
        去重置：`ensure_owner` 只看課程，不會察覺 `quiz_id` 來自別處。
        """
        return await db.scalar(
            select(EtQuiz)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .join(EtQuiz, EtQuiz.quiz_id == EtItem.quiz_id)
            .where(
                EtChapter.course_id == course_id,
                EtItem.quiz_id == quiz_id,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
                EtQuiz.deleted == 0,
            )
        )

    async def attempt_facts(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> tuple[int, bool]:
        """`(已提交 attempt 總數, 是否曾及格)`——供 `can_reset_retry` 判定。

        總數含**所有**已閱卷的 attempt（不扣重置基準），因為重置基準本身就要寫入這個
        總數；扣掉基準的「本輪已用次數」由 `round_used_attempts` 在呼叫端算。
        """
        total = await db.scalar(
            select(func.count(EtQuizAttemptM.attempt_id)).where(
                EtQuizAttemptM.user_id == user_id,
                EtQuizAttemptM.quiz_id == quiz_id,
                EtQuizAttemptM.status.in_(GRADED_STATUSES),
                EtQuizAttemptM.deleted == 0,
            )
        )
        passed = await db.scalar(
            select(func.count(EtQuizAttemptM.attempt_id)).where(
                EtQuizAttemptM.user_id == user_id,
                EtQuizAttemptM.quiz_id == quiz_id,
                EtQuizAttemptM.is_pass.is_(True),
                EtQuizAttemptM.deleted == 0,
            )
        )
        return total or 0, bool(passed)

    async def reset_base_of(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> int:
        """該學員於該測驗之重置基準（`MAX(ATTEMPT_COUNT_AT_RESET)`），無紀錄回 0。"""
        base = await db.scalar(
            select(func.max(EtQuizRetryReset.attempt_count_at_reset)).where(
                EtQuizRetryReset.user_id == user_id, EtQuizRetryReset.quiz_id == quiz_id
            )
        )
        return base or 0

    async def add_retry_reset(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        user_id: str,
        quiz_id: int,
        attempt_count: int,
        operator: OperatorInfo,
    ) -> None:
        """寫入一筆重置紀錄（**append-only，不刪任何 attempt**）。

        `ATTEMPT_COUNT_AT_RESET` 存重置當下的 attempt 總數作為新基準；之後
        `round_used_attempts(total, base)` 算出的本輪已用次數即從 0 起算。

        🔴 這是「重置次數歸 0」與「歷次 attempt 永久可回看」能並存的唯一做法
        （`data-model` 2026-08-19 為此新增本表）。**改成刪除 attempt 會同時毀掉學員的
        歷史與教師的追蹤資料**，而 AC 6 明訂重置後明細仍須完整。
        """
        now = utcnow()
        db.add(
            EtQuizRetryReset(
                course_id=course_id,
                user_id=user_id,
                quiz_id=quiz_id,
                attempt_count_at_reset=attempt_count,
                # `EXECUTED_BY` / `EXECUTED_AT` 是**業務語意**的執行者與時點（供 UI 查詢
                # 「誰在何時重置過」），與 `CREATED_*` 的資安稽核欄位並存、不互相取代
                # ——同一條原則見 `spec.md`「語意碼 vs. 業務紀錄表」。
                executed_by=operator.user_id,
                executed_at=now,
                created_user=operator.user_id,
                created_date=now,
            )
        )
        await db.flush()

    async def mark_removed(self, db: AsyncSession, enrollment: EtEnrollment, *, operator: OperatorInfo) -> None:
        """標記移除（`IS_REMOVED` + `REMOVED_AT`）——**軟刪，學習歷史完整保留**。

        `ET_PROGRESS` / `ET_QUIZ_ATTEMPT_M` 一律不動：FR-ET-US9-10 明訂歷史保留供稽核，
        且 AC 7 要求作答中的 attempt 仍可完成。
        """
        now = utcnow()
        enrollment.is_removed = True
        enrollment.removed_at = now
        enrollment.updated_user = operator.user_id
        enrollment.updated_date = now
        await db.flush()

    async def get_survey(self, db: AsyncSession, course_id: int) -> EtSurvey | None:
        """該課程之問卷（一門課 0~1 份）；無問卷回 `None`。"""
        return await db.scalar(select(EtSurvey).where(EtSurvey.course_id == course_id, EtSurvey.deleted == 0))

    async def survey_questions(self, db: AsyncSession, survey_id: int) -> list[EtSurveyQuestion]:
        """問卷題目（依 `SORT_ORDER`）。"""
        rows = await db.execute(
            select(EtSurveyQuestion)
            .where(EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0)
            .order_by(EtSurveyQuestion.sort_order.asc())
        )
        return list(rows.scalars().all())

    async def survey_options(self, db: AsyncSession, sq_ids: list[int]) -> dict[int, list[EtSurveyOption]]:
        """`{sq_id: [選項]}`——一次取回所有題目的選項，不逐題查。"""
        if not sq_ids:
            return {}
        rows = await db.execute(
            select(EtSurveyOption)
            .where(EtSurveyOption.sq_id.in_(sq_ids), EtSurveyOption.deleted == 0)
            .order_by(EtSurveyOption.sort_order.asc())
        )
        grouped: dict[int, list[EtSurveyOption]] = {}
        for option in rows.scalars().all():
            grouped.setdefault(option.sq_id, []).append(option)
        return grouped

    async def survey_responses(self, db: AsyncSession, survey_id: int) -> list[EtSurveyResponseM]:
        """該問卷的所有填答主檔（依提交時間）。"""
        rows = await db.execute(
            select(EtSurveyResponseM)
            .where(EtSurveyResponseM.survey_id == survey_id, EtSurveyResponseM.deleted == 0)
            .order_by(EtSurveyResponseM.submitted_at.asc())
        )
        return list(rows.scalars().all())

    async def survey_answers(self, db: AsyncSession, response_ids: list[int]) -> list[EtSurveyResponseD]:
        """所有填答明細——**一次取回**，供統計與明細兩種檢視共用。

        統計與明細是同一份資料的兩種呈現，查兩次會讓兩邊在併發填答時對不起來。
        """
        if not response_ids:
            return []
        rows = await db.execute(
            select(EtSurveyResponseD).where(
                EtSurveyResponseD.response_id.in_(response_ids), EtSurveyResponseD.deleted == 0
            )
        )
        return list(rows.scalars().all())

    async def enrolled_count(self, db: AsyncSession, course_id: int) -> int:
        """**在籍**學員數——已移除者不計入（比照完課率分母的定義）。"""
        total = await db.scalar(
            select(func.count(EtEnrollment.enrollment_id)).where(
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )
        return total or 0
