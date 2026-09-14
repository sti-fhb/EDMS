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
from app.et.course.rules import ensure_owner
from app.et.enrollment.rules import derive_completion_status
from app.et.tracking.repository import EtTrackingRepository
from app.et.tracking.schemas import EnrollmentRow, StudentRow

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")


class EtTrackingService:
    """教師端之學員學習狀況。"""

    def __init__(self, repository: EtTrackingRepository | None = None) -> None:
        self._repo = repository or EtTrackingRepository()

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
