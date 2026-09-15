"""週報逐學員明細下載端點（T164 / US14 / #325）。

授權：router-level 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`——單掛 `get_et_context`
等同「已登入」（學員角色於帳號建立當下即自動授予），不構成授權控制。細粒度的擁有權
判定在 service（教師僅限自己為 `OWNER_ID` 之課程）。

回應為 `utf-8-sig`：Excel 以系統 ANSI 編碼開啟無 BOM 的 UTF-8 CSV 會讓中文全部變亂碼，
而使用者只會看到「檔案壞了」。
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.schemas import MAX_INT4
from app.et.deps import EtContext, rate_limit_by_et_user, require_et_roles
from app.et.reports.service import EtReportsService
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

#: 每位使用者 / 每個 IP 每分鐘之明細匯出次數。
#:
#: **比 ET03 的瀏覽端點（180 / 600）緊得多**：這是匯出不是瀏覽，一次呼叫就拿到整批個資，
#: 正常使用不會連打。而它的工作量無上限——管理者不帶 `course_id` 時要對**全站**開放中
#: 課程各跑一輪聚合，全程佔住一條 DB 連線，而後端以 `--workers 1` 啟動。
_USER_RATE = 10
_IP_RATE = 60
_SCOPE = "et-report-export"

_user_limiter = SlidingWindowRateLimiter(max_requests=_USER_RATE, window_seconds=RATE_WINDOW_SECONDS)
_ip_limiter = SlidingWindowRateLimiter(max_requests=_IP_RATE, window_seconds=RATE_WINDOW_SECONDS)

router = APIRouter(
    prefix="/api/et/reports",
    tags=["et-reports"],
    dependencies=[
        Depends(rate_limit_by_et_user(_user_limiter, _SCOPE)),
        Depends(rate_limit_by_ip(_ip_limiter, _SCOPE)),
    ],
)

_service = EtReportsService()


@router.get("/weekly/students.csv")
async def download_weekly_students_csv(
    db: AsyncSession = Depends(get_db),
    ctx: EtContext = Depends(require_et_roles(ET_TEACHER, ET_ADMIN)),
    course_id: int | None = Query(
        default=None,
        ge=1,
        # BIGINT 上限：超出時 asyncpg 綁定參數會溢位成 500 而非 404（同 `course/schemas.py`）
        le=MAX_INT4,
        description="省略時為呼叫者權限範圍內的全部開放中課程（週報信中的連結即為此形式）",
    ),
) -> Response:
    """逐學員明細 CSV（FR-ET-US14-11）。

    內容於**請求當下即時查詢**產生，非寄信時的凍結檔，故可能與週報內文的摘要有時間差
    （範本內文已註明此點）。
    """
    content = await _service.weekly_csv(db, ctx=ctx, course_id=course_id)
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="et-weekly-students.csv"'},
    )
