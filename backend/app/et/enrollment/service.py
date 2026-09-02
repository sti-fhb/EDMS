"""ET04 我的課程與加入新課程 Service（US4 / #247）。

## `preview` 不是把關

`join()` **必定重跑全部驗證**，不因前端已呼叫過 `preview()` 而略過。預覽只是體驗
（AC 6 要求「先顯示課程資訊、確認後才加入」），把它當成把關等於讓任何直接打
`POST /enrollments` 的請求繞過課程狀態與成員資格檢查。比照 #204 的
`publish-check` 與 `publish`。

## 學員無退場能力

本模組**刻意沒有 delete / leave**（FR-ET-US4-06）。退場僅能由教師於 US9 執行
「移除學員」。少寫一個端點就是這條規則的執行方式——寫了再用權限擋，下一個人會
以為它只是暫時關著。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    COMPLETION_NOT_STARTED,
    SOURCE_INVITATION_CODE,
)
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.enrollment.rules import (
    ensure_course_joinable,
    ensure_not_removed,
    is_listed_in_my_courses,
    normalize_invitation_code,
)
from app.et.enrollment.schemas import (
    JoinPreview,
    JoinResult,
    MyCourseRow,
    MyCoursesResult,
    MyCoursesSummary,
)
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-ENROLLMENT"

_CODE_INVALID = AppError(status_code=404, detail="邀請碼無效，請確認後重試", error_code="ET_ENROLL_001")

#: 卡片進度百分比。**本 issue 恆為 0**——進度累積依賴 `ET_PROGRESS`（`ET-5`）。
_PROGRESS_NOT_IMPLEMENTED = 0


class EtEnrollmentService:
    """學員端選課：我的課程清單、邀請碼預覽與加入。"""

    def __init__(
        self,
        enrollments: EtEnrollmentRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._audit = audit or AuditLogService()

    async def my_courses(self, db: AsyncSession, *, user_id: str) -> MyCoursesResult:
        """我的課程清單與統計（AC 2 / AC 3 / AC 4 / AC 5）。

        統計由**過濾後**的清單導出，不另外查一次 count——兩者分開查會在課程剛到
        開放時間或剛被關閉的瞬間出現「卡片 3 門、統計寫 2 門」的不一致。
        """
        now = utcnow()
        visible = [
            (enrollment, course)
            for enrollment, course in await self._enrollments.list_active_enrollments(db, user_id)
            if is_listed_in_my_courses(status=course.status, open_start_at=course.open_start_at, now=now)
        ]

        course_ids = [course.course_id for _, course in visible]
        tags = await self._enrollments.tags_by_course(db, course_ids)
        chapters = await self._enrollments.chapter_counts(db, course_ids)

        courses = [
            MyCourseRow(
                course_id=course.course_id,
                course_name=course.course_name,
                status=course.status,
                completion_status=enrollment.completion_status,
                tags=tags.get(course.course_id, []),
                chapter_count=chapters.get(course.course_id, 0),
                open_start_at=course.open_start_at,
                open_end_at=course.open_end_at,
                progress_pct=_PROGRESS_NOT_IMPLEMENTED,
            )
            for enrollment, course in visible
        ]
        return MyCoursesResult(summary=_summarize(courses), courses=courses)

    async def preview(self, db: AsyncSession, *, code: str, user_id: str) -> JoinPreview:
        """驗證邀請碼並回課程資訊，**不寫入任何資料**（AC 6）。

        Raises:
            AppError: 404 `ET_ENROLL_001` 邀請碼無效；409 `ET_ENROLL_002` 課程關閉中；
                409 `ET_ENROLL_003` 已被移除出此課程。
        """
        course = await self._require_course(db, code)
        enrollment = await self._enrollments.get_enrollment(db, user_id=user_id, course_id=course.course_id)
        if enrollment is not None:
            # 順序要緊：先擋「已被移除」（裁示 C），再讓「已加入」走正常導航。
            # 反過來的話被移除者會拿到 already_joined=true，前端把他導向一門他已無
            # 成員資格的課程。
            ensure_not_removed(is_removed=enrollment.is_removed)

        return JoinPreview(
            course_id=course.course_id,
            course_name=course.course_name,
            owner_name=await self._enrollments.owner_name(db, course.owner_id),
            chapter_count=await self._enrollments.chapter_count(db, course.course_id),
            already_joined=enrollment is not None,
            open_start_at=course.open_start_at,
        )

    async def join(self, db: AsyncSession, *, code: str, operator: OperatorInfo) -> JoinResult:
        """確認加入課程（AC 7 / ET-MSG-ET04-004）。

        起始時間未到之課程**仍可加入**（#247 SA Q2 裁示 A）；`pending_open` 讓前端
        把提示換成「已加入，課程開放後將出現於清單」，否則學員會加入成功卻在清單
        看不到課程（AC 4），以為失敗而反覆重試。

        Raises:
            AppError: 同 `preview`。已加入者**不視為錯誤**，回既有選課列（AC 10）。
        """
        course = await self._require_course(db, code)
        existing = await self._enrollments.get_enrollment(db, user_id=operator.user_id, course_id=course.course_id)
        if existing is not None:
            ensure_not_removed(is_removed=existing.is_removed)
            # 重複加入不重複寫入、也不報錯——AC 10 要的是「導向該課程」。
            return _to_result(course, existing.completion_status)

        await self._enrollments.create(
            db,
            user_id=operator.user_id,
            course_id=course.course_id,
            join_source=SOURCE_INVITATION_CODE,
            completion_status=COMPLETION_NOT_STARTED,
            joined_at=utcnow(),
            operator=operator,
        )
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=str(course.course_id),
            description="以邀請碼加入課程",
        )
        return _to_result(course, COMPLETION_NOT_STARTED)

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_course(self, db: AsyncSession, code: str):
        """邀請碼 → 課程，含格式與狀態檢核。

        格式不符**不查 DB**：8 碼純數字以外的輸入不可能命中（欄位為 `VARCHAR(8)`），
        直接回「邀請碼無效」與查無的回應一致，也不必為此走一趟資料庫。
        """
        normalized = normalize_invitation_code(code)
        if normalized is None:
            raise _CODE_INVALID
        course = await self._enrollments.get_by_invitation_code(db, normalized)
        if course is None:
            raise _CODE_INVALID
        ensure_course_joinable(course_status=course.status)
        return course


def _to_result(course, completion_status: str) -> JoinResult:
    return JoinResult(
        course_id=course.course_id,
        completion_status=completion_status,
        pending_open=course.open_start_at is not None and utcnow() < course.open_start_at,
    )


def _summarize(courses: list[MyCourseRow]) -> MyCoursesSummary:
    """由清單導出四項統計（AC 2）。

    以 `COMPLETION_STATUS` 分類（`data-model` §ET_COMPLETION_STATUS）。未知值不計入
    三項分類但仍計入 `joined`——分類漏一個值時卡片仍在畫面上，統計卻靜默少一，
    總數與三項之和不符正是那種情況的訊號。
    """
    return MyCoursesSummary(
        joined=len(courses),
        in_progress=sum(1 for c in courses if c.completion_status == COMPLETION_IN_PROGRESS),
        not_started=sum(1 for c in courses if c.completion_status == COMPLETION_NOT_STARTED),
        completed=sum(1 for c in courses if c.completion_status == COMPLETION_COMPLETED),
    )
