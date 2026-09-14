"""ET03 學員學習狀況追蹤 API（US9 / #322）——教師端。

router-level 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`；擁有權另由 service 的
`ensure_owner` 判定。兩層都要：角色閘擋掉學員，擁有權閘擋掉「別的教師」。

本模組的回應含**學員個別成績與具名問卷填答**，是 ET 模組個資密度最高的一處
（`FR-ET-US9-08`），故授權比照課程編輯端點從嚴，不因為是「唯讀查詢」而放寬。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.pagination import PagedResponse
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER
from app.et.tracking.schemas import StudentRow
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
    return await _service.list_students(db, course_id, actor_id=ctx.user_id, page=page, limit=limit)
