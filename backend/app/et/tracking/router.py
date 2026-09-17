"""ET03 學員學習狀況追蹤 API（US9 / #322）——教師端。

router-level 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`；擁有權另由 service 的
`ensure_owner` 判定。兩層都要：角色閘擋掉學員，擁有權閘擋掉「別的教師」。

本模組的回應含**學員個別成績與具名問卷填答**，是 ET 模組個資密度最高的一處
（`FR-ET-US9-08`），故授權比照課程編輯端點從嚴，不因為是「唯讀查詢」而放寬。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER
from app.et.tracking.schemas import (
    AttemptOverview,
    RetryResetResult,
    StudentRow,
    SurveyResult,
    TeacherAttemptDetail,
)
from app.et.tracking.service import EtTrackingService

#: 每位使用者 / 每個 IP 每分鐘之教師端查詢數。
#:
#: 比學員端寬鬆——教師會頻繁切換課程與展開區塊，一次操作可能打好幾支端點；但仍要有
#: 上限，本模組的回應含全班成績，是值得防的抓取目標。
_USER_RATE = 180
_IP_RATE = 600

_SCOPE = "et-tracking"

_user_limiter = SlidingWindowRateLimiter(max_requests=_USER_RATE, window_seconds=RATE_WINDOW_SECONDS)
_ip_limiter = SlidingWindowRateLimiter(max_requests=_IP_RATE, window_seconds=RATE_WINDOW_SECONDS)

router = APIRouter(
    prefix="/api/et",
    tags=["ET 學員追蹤"],
    dependencies=[
        Depends(get_et_context),
        Depends(rate_limit_by_et_user(_user_limiter, _SCOPE)),
        Depends(rate_limit_by_ip(_ip_limiter, _SCOPE)),
    ],
)

_service = EtTrackingService()


@router.get(
    "/courses/{course_id}/students",
    response_model=PagedResponse[StudentRow],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def list_students(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PagedResponse[StudentRow]:
    """區塊 1：該課程之已加入學員清單（`FR-ET-US9-02` / `-03`）。

    **已移除者不列入**（`IS_REMOVED`），但其學習歷史完整保留於 DB 供稽核。

    `completion_status` 與 `progress_pct` 為**即時計算**——`ET_ENROLLMENT` 的同名欄位
    只有加入時寫入的 `NOT_STARTED`、沒有推進路徑，讀它會讓全班永遠顯示「未開始」。

    `avg_score` 為**已作答測驗**之最高分平均；完全未作答時回 `null`（前端顯示「—」，
    不可顯示 0——0 分與未作答意義相反）。
    """
    return await _service.list_students(
        db, course_id, actor_id=ctx.user_id, actor_roles=ctx.roles, page=page, limit=limit
    )


@router.get(
    "/courses/{course_id}/attempt-overview",
    response_model=AttemptOverview,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def attempt_overview(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> AttemptOverview:
    """區塊 2：所有**曾作答**學員 × 各測驗之 attempt 摘要（`FR-ET-US9-04`）。

    **不分頁**——規格明訂「一次列出所有曾作答之學員（不設學員篩選）」，且本區塊為
    摺疊式，一次載入的是摘要而非逐題明細。

    已作答學員的**未作答測驗仍會列出**（`attempts` 為空）：整個測驗不出現的話，教師
    分不出「他沒考」與「這門課沒這個測驗」。
    """
    return await _service.attempt_overview(db, course_id, actor_id=ctx.user_id, actor_roles=ctx.roles)


@router.get(
    "/attempts/{attempt_id}/detail",
    response_model=TeacherAttemptDetail,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def attempt_detail(
    attempt_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> TeacherAttemptDetail:
    """區塊 2：教師端檢視單次 attempt 的逐題明細（`FR-ET-US9-05`）。

    ⚠️ **與學員端 `GET /attempts/{id}/result` 是不同的端點、不同的授權**：那支以
    `USER_ID` 比對（只能看自己的），本支以「該 attempt 所屬課程的擁有者」判定。
    **不可**為了複用而放寬學員端那支——那會讓任何學員拿 `attempt_id` 就能看別人的考卷。

    逐題內容依該次 attempt 的快照渲染，與學員端同一支組裝函式：同一份資料兩端必須長得
    一樣，否則教師與學員對著同一次作答會看到不同的對錯。
    """
    return await _service.attempt_detail(db, attempt_id, actor_id=ctx.user_id, actor_roles=ctx.roles)


@router.post(
    "/courses/{course_id}/students/{user_id}/quizzes/{quiz_id}/retry-reset",
    response_model=RetryResetResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def reset_retry(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    user_id: Annotated[str, Path(max_length=20, pattern=r"^[A-Za-z0-9_.\-]+$")],
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> RetryResetResult:
    """重置某學員於某測驗之重考次數（`FR-ET-US9-06`）。

    **以測驗為單位**，非整門課一次重置（AC 19 明訂）。僅當該學員於該測驗之已用次數
    用盡且尚未及格時可執行，否則 409 `ET_TRACK_002`。

    🔴 **不刪除任何 attempt**——以 `ET_QUIZ_RETRY_RESET` 記基準達成「次數歸 0」，讓
    「歷次明細永久可回看」與之並存。

    課程視同關閉（含期間已過）時 409 `ET_TRACK_003`。
    """
    return await _service.reset_retry(db, course_id, user_id, quiz_id, operator=operator)


@router.delete(
    "/courses/{course_id}/students/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def remove_student(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    user_id: Annotated[str, Path(max_length=20, pattern=r"^[A-Za-z0-9_.\-]+$")],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """移除課程學員（`FR-ET-US9-10`）——軟刪，**學習歷史完整保留供稽核**。

    有 `IN_PROGRESS` attempt 時**仍允許移除**，該 attempt 保留並可完成（AC 7）；警告
    文案 ET-MSG-ET03-003 由前端顯示。

    已移除者回 404 `ET_TRACK_001`：重複移除代表教師的清單已過期，靜默成功會誤導他。

    課程視同關閉（含期間已過）時 409 `ET_TRACK_003`。
    """
    await _service.remove_student(db, course_id, user_id, operator=operator)


@router.get(
    "/courses/{course_id}/survey-result",
    response_model=SurveyResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def survey_result(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> SurveyResult:
    """區塊 3：問卷結果之統計與明細（`FR-ET-US9-07`）。

    🔴 **具名資料**（`FR-ET-US9-08`）：僅本課程教師與管理者可見。

    課程無問卷時回 `has_survey=false`（前端據此隱藏整個區塊），**不回 404**——那會讓
    前端分不出「這門課沒問卷」與「你沒權限」。

    統計檢視之**問答題僅回已答人數、不回文字**（2026-08-28 裁示）；文字答案在明細檢視。
    """
    return await _service.survey_result(db, course_id, actor_id=ctx.user_id, actor_roles=ctx.roles)


@router.get(
    "/courses/{course_id}/students.csv",
    response_class=Response,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def export_students_csv(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """匯出區塊 1 之學員清單（`FR-ET-US9-09`）——**全量**，不受畫面分頁限制。

    課程已關閉時**仍可匯出**（AC 10 明訂）——匯出是讀不是寫，套上寫入閘會讓教師在
    課程結束後拿不走自己的教學紀錄。
    """
    content = await _service.export_students_csv(db, course_id, actor_id=ctx.user_id, actor_roles=ctx.roles)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="course-{course_id}-students.csv"'},
    )


@router.get(
    "/courses/{course_id}/survey-result.csv",
    response_class=Response,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def export_survey_csv(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """匯出區塊 3 之問卷結果（`FR-ET-US9-09`）——**含問答題之文字答案**。

    🔴 **具名資料**（`FR-ET-US9-08`）：僅本課程教師與管理者可匯出。CSV 是最容易被當成
    「只是下載」而漏掉把關的入口。

    課程無問卷時 404——回只有表頭的空檔案會讓教師以為「沒有人填」。
    """
    content = await _service.export_survey_csv(db, course_id, actor_id=ctx.user_id, actor_roles=ctx.roles)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="course-{course_id}-survey.csv"'},
    )
