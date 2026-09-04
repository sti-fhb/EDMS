"""ET04 我的課程與加入新課程 API（US4 / #247）。

router-level 只掛 `get_et_context`，**不掛 `require_et_roles(ET_STUDENT)`**——ET 學員
角色於帳號建立當下即自動授予、存量帳號亦由 bootstrap seed 回填（`deps.py` 已載明），
故加掛學員角色不會擋掉任何人，只會讓讀者以為這裡有實質授權。

真正的授權在資料本身：所有查詢都以 `ctx.user_id` 過濾，沒有「查別人的課程」的參數
可傳。

## 為何 preview 是 POST 而非 GET

邀請碼是憑證。放在 query string 會進 access log、瀏覽器歷史與 Referer；
即使沒有寫入，它也不該出現在 URL 裡。

## 邀請碼枚舉面與限流

邀請碼只有 8 碼純數字（10^8），而上一段說明了**任何已登入者都能打這兩個端點**。
`preview` 的 200 / 404 差異可直接判斷一組碼是否有效，`join` 也是同樣精度的判定
oracle（它會把 `_require_course` 整套重跑）。而 `join` 沒有「必須先被邀請」的額外
檢查——拿到有效碼即可加入，那正是邀請碼的設計。碼一旦被枚舉出來，等同繞過整個
邀請門檻。

⚠️ **該算的不是「掃完 10^8 要多久」，是「打中任何一組有效碼要多久」**。全站若有
200 門已發布課程，期望試行約 5×10^5 次——用「全空間 ÷ 速率」估會嚴重高估安全性。

兩個維度**同時**掛（比照 `dp/user/router.py` 的 login 同時掛 IP 與帳號）：

- **使用者維度為主**：攻擊者是已登入帳號，這個維度才對得上。
- **IP 維度為輔、門檻放寬**：使用者維度可用「多開帳號」線性擴張（自助註冊是開的），
  只掛使用者維度等於留一條可線性放大的路。IP 門檻放寬到不會誤傷同一 NAT 下正常
  同時操作的同事。

`preview` 與 `join` **共用同一個分桶**——分開會讓額度加倍，而兩者是同一件事的兩半。
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.deps import EtContext, get_et_context
from app.et.enrollment.schemas import JoinByCodeReq, JoinPreview, JoinResult, MyCoursesResult
from app.et.enrollment.service import EtEnrollmentService

#: 每位使用者每分鐘可嘗試的邀請碼次數（`preview` 與 `join` 合計）。
#:
#: 正常使用者一次輸入一組碼、偶爾打錯重來；開學時教師可能一次發數組碼，故比
#: `LOGIN_RATE_MAX`（10，單一表單重試）寬鬆。
_ENROLL_RATE_MAX = 20

#: 同一 IP 每分鐘之合計上限。刻意寬鬆——同辦公室（同一 NAT 出口）可能有數十人同時
#: 加入課程，此維度的作用是擋住「多開帳號線性放大」，不是管制個別使用者。
_ENROLL_IP_RATE_MAX = 120

_enroll_limiter = SlidingWindowRateLimiter(max_requests=_ENROLL_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_enroll_ip_limiter = SlidingWindowRateLimiter(max_requests=_ENROLL_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

#: 兩端點共用之分桶前綴。**不要把端點名組進去**——`preview` 與 `join` 是同一件事的
#: 兩半，分開計數會讓實際額度變成兩倍，而註解上的門檻卻只寫一份。
_ENROLL_SCOPE = "et-enroll"


def rate_limit_by_user(scope: str) -> Callable[..., Awaitable[None]]:
    """依 `USER_ID` 限流之 dependency（`core.rate_limit` 只提供 IP 維度）。

    Raises:
        AppError: 視窗內超過門檻（429 / `COMMON_429`）。
    """

    async def _dependency(ctx: EtContext = Depends(get_et_context)) -> None:
        _enroll_limiter.hit(f"{scope}:user:{ctx.user_id}")

    return _dependency


router = APIRouter(
    prefix="/api/et",
    tags=["et-enrollment"],
    dependencies=[Depends(get_et_context)],
)
_service = EtEnrollmentService()


@router.get("/my-courses", response_model=MyCoursesResult)
async def my_courses(
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> MyCoursesResult:
    """ET04 我的課程：四項統計 + 課程卡片清單。

    起始時間未到之課程不出現（AC 4）；已關閉課程仍出現並帶 `status=CLOSED`（AC 5）。
    """
    return await _service.my_courses(db, user_id=ctx.user_id)


@router.post(
    "/enrollments/preview",
    response_model=JoinPreview,
    dependencies=[
        Depends(rate_limit_by_user(_ENROLL_SCOPE)),
        Depends(rate_limit_by_ip(_enroll_ip_limiter, _ENROLL_SCOPE)),
    ],
)
async def preview_enrollment(
    req: JoinByCodeReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> JoinPreview:
    """驗證邀請碼並回課程資訊，**不寫入**（AC 6）。

    已加入者以 `already_joined=true` 表示（200），非錯誤——那是正常導航（AC 10）。
    """
    return await _service.preview(db, code=req.invitation_code, user_id=ctx.user_id)


@router.post(
    "/enrollments",
    response_model=JoinResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(rate_limit_by_user(_ENROLL_SCOPE)),
        Depends(rate_limit_by_ip(_enroll_ip_limiter, _ENROLL_SCOPE)),
    ],
)
async def join_course(
    req: JoinByCodeReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> JoinResult:
    """確認加入課程，`JOIN_SOURCE = INVITATION_CODE`（AC 7）。

    **重跑 `preview` 的全部驗證**——預覽是體驗，不是把關。
    """
    return await _service.join(db, code=req.invitation_code, operator=operator)
