"""ET02 邀請學員 API（US8 / #273、#362）。

## 為何預覽與寄送都是 POST

收件人清單是個資。放在 query string 會進 access log、瀏覽器歷史與 Referer——即使
不寫入任何地方，它也不該出現在 URL 裡。同 `enrollment/router.py` 對邀請碼的判斷。

## 限流：`send` / `preview` 共用同一個使用者維度分桶

`send` 每次可對最多 50 個**任意網域**的位址寫入 outbox，若無次數上限，本系統就成了一個
「發送者身分完全合法（SPF / DKIM 皆通過本組織網域）」的對外投遞管道——即使信件內容
不可控，SMTP 資源、`DP_EMAIL_LOG` 膨脹與組織信譽（退信率）仍是實質的濫用面。`preview`
共用同一分桶：兩者是同一件事的兩半，分開計數會讓實際額度變成兩倍。

⚠️ **#362 起這個額度不只限寄信速率，也限「加人」速率**：`send` 現在會直接寫
`ET_ENROLLMENT`，同時也是「一次貼 50 筆 Email、看哪些有帳號」這個探測面的速率上限。
調整額度時三件事要一起想，不能只算 outbox。

## 授權

`require_et_roles(TEACHER, ADMIN)` + service 層 `ensure_owner`（擁有權要先讀出課程才
知道，無法用 dependency 表達）。兩支端點都經 `_require_invitable_course`，沒有例外路徑。

> #362 之前還有一支 `POST /et/invitations/accept`（受邀者點信中連結加入），它**不掛限流**
> 且只驗 token。邀請即加入之後整支移除——沒有要接受的東西了。
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.invitation.schemas import (
    EmailInviteReq,
    EmailInviteResult,
    InvitePreview,
)
from app.et.invitation.service import EtInvitationService
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

#: 每位教師每分鐘之邀請操作次數（`preview` 與 `send` 合計）。
#:
#: 正常流程一次邀請要打 2 支（下一步 → 確認寄出），改一次清單再送就是 4 支；門檻取 12
#: 讓連續修正幾輪都不會誤傷，但把「以最大 50 筆連續灌 outbox」壓在每分鐘 600 個收件人以內。
_INVITE_RATE_MAX = 12

_invite_limiter = SlidingWindowRateLimiter(max_requests=_INVITE_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

#: `preview` 與 `send` 共用之分桶。**不要把端點名組進去**——兩者是同一件事的兩半，
#: 分開計數會讓實際額度變成兩倍，而註解上的門檻卻只寫一份（同 `enrollment` 之 `_ENROLL_SCOPE`）。
_INVITE_SCOPE = "et-invite"


def rate_limit_invites() -> Callable[..., Awaitable[None]]:
    """依 `USER_ID` 限流之 dependency（`core.rate_limit` 只提供 IP 維度）。

    刻意**不與 `enrollment/router.py` 的 `rate_limit_by_user` 共用**：那一支把限流器
    closure 在模組層變數裡、簽章為 `(scope)`，抽成共用工廠得改它的簽章，而 #247 的
    `tests/unit/et/test_enrollment_rate_limit.py` 正是以該簽章呼叫。為了省 6 行而去動
    另一個 issue 已測過的介面不划算。

    Raises:
        AppError: 視窗內超過門檻（429 / `COMMON_429`）。
    """

    async def _dependency(ctx: EtContext = Depends(get_et_context)) -> None:
        _invite_limiter.hit(f"{_INVITE_SCOPE}:user:{ctx.user_id}")

    return _dependency


router = APIRouter(prefix="/api/et", tags=["et-invitation"], dependencies=[Depends(get_et_context)])
_service = EtInvitationService()


@router.post(
    "/courses/{course_id}/invitations/preview",
    response_model=InvitePreview,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), Depends(rate_limit_invites())],
)
async def preview_invitation(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: EmailInviteReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> InvitePreview:
    """邀請信預覽（唯讀，AC 6）——主旨與內文由管理者於 DP 後台統一維護，教師不可編輯。"""
    return await _service.preview(db, course_id, raw_emails=req.emails, actor_id=ctx.user_id)


@router.post(
    "/courses/{course_id}/invitations",
    response_model=EmailInviteResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), Depends(rate_limit_invites())],
)
async def send_invitations(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: EmailInviteReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> EmailInviteResult:
    """寄出 Email 邀請（AC 6）。

    **重跑預覽的全部驗證**——預覽是體驗，不是把關（比照 `enrollment` 的 preview/join）。
    """
    return await _service.send(db, course_id, raw_emails=req.emails, operator=operator)
