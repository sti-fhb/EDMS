"""ET03 學員學習狀況追蹤 Service（US9 / #322）。

**授權兩層**：router 層 `require_et_roles(ET_TEACHER, ET_ADMIN)`，service 層
`ensure_owner`——`FR-ET-US9-08` 明訂問卷填答為具名資料，其統計與明細僅本課程教師與
管理者可見，而本頁其餘兩區塊同樣含學員的個別成績，故一律同等把關。
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.pagination import PaginatedResult, paginate
from app.et.attempt.repository import EtAttemptRepository
from app.et.attempt.rules import round_used_attempts
from app.et.attempt.service import _in_snapshot_order, _to_result
from app.et.course.rules import ensure_owner
from app.et.enrollment.rules import derive_completion_status
from app.et.tracking.repository import EtTrackingRepository
from app.et.tracking.rules import can_reset_retry
from app.et.tracking.schemas import (
    AttemptOverview,
    EnrollmentRow,
    StudentRow,
    TeacherAttemptDetail,
    TeacherAttemptRow,
    TeacherQuizRow,
    TeacherStudentAttempts,
)

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_ATTEMPT_NOT_FOUND = AppError(status_code=404, detail="查無此作答紀錄", error_code="ET_ATTEMPT_001")


class EtTrackingService:
    """教師端之學員學習狀況。"""

    def __init__(
        self,
        repository: EtTrackingRepository | None = None,
        attempts: EtAttemptRepository | None = None,
    ) -> None:
        self._repo = repository or EtTrackingRepository()
        # 重用 attempt 模組的查詢（配分總和、逐題明細）——那些是同一份資料，
        # 各寫一份遲早與學員端分岔，而分岔的表現是同一次作答兩邊分數不同。
        self._attempts = attempts or EtAttemptRepository()

    async def list_students(
        self, db: AsyncSession, course_id: int, *, actor_id: str, page: int, limit: int
    ) -> PaginatedResult[StudentRow]:
        """區塊 1：已加入學員清單（`FR-ET-US9-02` / `-03`）。

        ## 先 `paginate()`，再以該頁的 `user_id` 批次補齊

        一頁十幾位學員，每人要算完課數、平均成績、最後活動——逐筆再查就是幾十次往返。
        三次固定成本的查詢與頁面筆數無關。

        ⚠️ 三個聚合**刻意分開查**：把它們併進同一個 `GROUP BY` 會讓兩個一對多關聯互相
        灌大彼此的計數（2 項目 × 3 次作答 → 兩個數字都變 6）。
        """
        await self._require_owner(db, course_id, actor_id)

        stmt = self._repo.build_student_list_stmt(course_id=course_id)
        paged = await paginate(db, stmt, page=page, limit=limit, schema=EnrollmentRow)
        enrollments: list[EnrollmentRow] = paged["data"]
        user_ids = [e.user_id for e in enrollments]

        counts = await self._repo.completion_counts_by_student(db, course_id=course_id, user_ids=user_ids)
        avg_scores = await self._repo.avg_best_score_by_student(db, course_id=course_id, user_ids=user_ids)
        last_submits = await self._repo.last_submitted_at_by_student(db, course_id=course_id, user_ids=user_ids)
        names = await self._repo.user_names(db, set(user_ids))

        rows = [
            _to_student_row(
                e,
                counts=counts.get(e.user_id, (0, 0)),
                avg_score=avg_scores.get(e.user_id),
                last_submitted_at=last_submits.get(e.user_id),
                user_name=names.get(e.user_id),
            )
            for e in enrollments
        ]
        return {"data": rows, "meta": paged["meta"]}

    async def _require_owner(self, db: AsyncSession, course_id: int, actor_id: str) -> None:
        """課程存在且操作者為擁有者，否則 404 / 403。"""
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)

    async def attempt_overview(self, db: AsyncSession, course_id: int, *, actor_id: str) -> AttemptOverview:
        """區塊 2：所有曾作答學員 × 各測驗之 attempt 摘要（`FR-ET-US9-04`）。

        ## 三次查詢取全班，不逐學員

        測驗清單、全課程 attempt、重置基準各一次。逐學員查是 N+1，而本區塊「一次列出
        所有曾作答之學員」是規格明訂（不設學員篩選）。

        ## 只列**曾作答**的學員

        未作答者不進本區塊——他在區塊 1 仍然看得到。但**已作答學員的未作答測驗要列出**
        （`attempts` 為空 + `ET-MSG-ET03-005`「尚未作答」），否則教師分不出「他沒考」
        與「這門課沒這個測驗」。
        """
        await self._require_owner(db, course_id, actor_id)

        quizzes = await self._repo.quizzes_of_course(db, course_id)
        attempts = await self._repo.attempts_of_course(db, course_id)
        reset_bases = await self._repo.reset_bases_of_course(db, course_id)
        points = await self._attempts.points_total_by_attempt(db, [a.attempt_id for a in attempts])

        by_user: dict[str, dict[int, list]] = {}
        for a in attempts:
            by_user.setdefault(a.user_id, {}).setdefault(a.quiz_id, []).append(a)
        names = await self._repo.user_names(db, set(by_user))

        students = [
            TeacherStudentAttempts(
                user_id=user_id,
                user_name=names.get(user_id),
                quizzes=[
                    _to_quiz_row(
                        quiz,
                        attempts=per_quiz.get(quiz.quiz_id, []),
                        reset_base=reset_bases.get((user_id, quiz.quiz_id), 0),
                        points=points,
                    )
                    for quiz in quizzes
                ],
            )
            for user_id, per_quiz in by_user.items()
        ]
        return AttemptOverview(students=students)

    async def attempt_detail(self, db: AsyncSession, attempt_id: int, *, actor_id: str) -> TeacherAttemptDetail:
        """區塊 2：教師端檢視單次 attempt 之逐題明細（`FR-ET-US9-05`）。

        ## 授權以「該 attempt 所屬課程的擁有者」判定

        ⚠️ 與學員端 `attempt/service._require_own_attempt` **不同**：那支比對 `USER_ID`
        （只能看自己的考卷），教師要看的正是別人的。但**不可放寬成「任何教師都能看」**
        ——那等於全站考卷對所有教師公開。

        ## 依快照渲染，不回查題庫

        `_to_result` 讀的全是 `ET_QUIZ_ATTEMPT_D` 的 `*_SNAPSHOT` 欄位（與學員端同一支
        函式）。回查 `ET_QUESTION` / `ET_OPTION` 會讓教師改過配分或正確答案之後，歷史
        明細靜默變樣（`spec_us6` 場景 26）。
        """
        found = await self._repo.get_attempt_with_course(db, attempt_id)
        if found is None:
            raise _ATTEMPT_NOT_FOUND
        attempt, course = found
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)

        quiz = await self._attempts.get_quiz(db, attempt.quiz_id)
        details = await self._attempts.list_details(db, attempt_id)
        names = await self._repo.user_names(db, {attempt.user_id})
        ordered = _in_snapshot_order(details, attempt.question_order)
        return TeacherAttemptDetail(
            attempt_id=attempt.attempt_id,
            user_id=attempt.user_id,
            user_name=names.get(attempt.user_id),
            quiz_name=quiz.quiz_name if quiz else "",
            attempt_no=attempt.attempt_no,
            submitted_at=attempt.submitted_at or attempt.started_at,
            score=attempt.score if attempt.score is not None else Decimal(0),
            points_total=sum(d.points_snapshot for d in details),
            pass_score=attempt.pass_score_snapshot,
            is_pass=bool(attempt.is_pass),
            questions=[_to_result(d, d.score if d.score is not None else Decimal(0)) for d in ordered],
        )


def _to_student_row(
    enrollment: EnrollmentRow,
    *,
    counts: tuple[int, int],
    avg_score: float | None,
    last_submitted_at: datetime | None,
    user_name: str | None,
) -> StudentRow:
    """組一列學員。`counts` 為 `(完成項目數, 總項目數)`。"""
    done, total = counts
    return StudentRow(
        user_id=enrollment.user_id,
        user_name=user_name,
        joined_at=enrollment.joined_at,
        # 即時導出——**不讀** `enrollment.completion_status`，那個欄位只有加入時寫入的
        # `NOT_STARTED`，沒有任何路徑推進它（同 ET04 於 #284 的處理）
        completion_status=derive_completion_status(done=done, total=total),
        progress_pct=_pct(done, total),
        avg_score=_round2(avg_score),
        # `LAST_ACTIVITY_AT` 不含測驗提交（只在檢視項目時更新），取兩者較晚者
        last_activity_at=_latest(enrollment.last_activity_at, last_submitted_at),
    )


def _pct(done: int, total: int) -> int:
    """完成百分比（四捨五入）。

    ⚠️ **完課判定不可用這個值**——201 個項目完成 200 個時它回 100
    （見 `enrollment/rules.is_course_completed` 的說明）。此處僅供顯示。
    """
    if total <= 0:
        return 0
    return round(done * 100 / total)


def _round2(value: float | None) -> Decimal | None:
    """平均成績取兩位小數；`None` 原樣回傳（＝完全未作答，前端顯示「—」）。"""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _latest(*values):
    """取非 `None` 者中最晚的一個；全為 `None` 時回 `None`。"""
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _to_quiz_row(quiz, *, attempts: list, reset_base: int, points: dict[int, int]) -> TeacherQuizRow:
    """組某學員於某測驗的一列。`attempts` 為空即「尚未作答」。

    `used_attempts` 走 `round_used_attempts`（總數扣掉重置基準）——直接用 `len(attempts)`
    會讓重置過的學員顯示「已用 5 次」而他的配額其實剛歸零。
    """
    used = round_used_attempts(total=len(attempts), reset_base=reset_base)
    is_passed = any(bool(a.is_pass) for a in attempts)
    return TeacherQuizRow(
        quiz_id=quiz.quiz_id,
        quiz_name=quiz.quiz_name,
        max_retry=quiz.max_retry,
        used_attempts=used,
        is_passed=is_passed,
        # 由後端判定——前端自行推導會複製一份規則，而規則會變
        can_reset=can_reset_retry(used=used, max_retry=quiz.max_retry, is_passed=is_passed, has_attempt=bool(attempts)),
        attempts=[
            TeacherAttemptRow(
                attempt_id=a.attempt_id,
                attempt_no=a.attempt_no,
                submitted_at=a.submitted_at or a.started_at,
                score=a.score if a.score is not None else Decimal(0),
                points_total=points.get(a.attempt_id, 0),
                is_pass=bool(a.is_pass),
            )
            for a in attempts
        ],
    )
