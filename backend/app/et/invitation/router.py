"""ET02 邀請學員 API（US8 / #273）。

## 為何預覽與寄送都是 POST

收件人清單是個資。放在 query string 會進 access log、瀏覽器歷史與 Referer——即使
不寫入任何地方，它也不該出現在 URL 裡。同 `enrollment/router.py` 對邀請碼的判斷。

## 為何 accept 不掛限流

`enrollment` 的邀請碼端點掛了雙維度限流，因為 8 碼純數字只有 10^8 種、且 200/404 的
差異就是一個可枚舉的 oracle。邀請 token 是 `secrets.token_urlsafe(32)`（256 bits），
枚舉不可行——為它加限流只會在正常使用者反覆點信中連結時誤傷，卻擋不到任何實際攻擊。

**不為不存在的情境寫防禦碼**（`sti-coding-style`）。

## 授權

- 預覽 / 寄送：`require_et_roles(TEACHER, ADMIN)` + service 層 `ensure_owner`
  （擁有權要先讀出課程才知道，無法用 dependency 表達）。
- accept：只掛 `get_et_context`——受邀者就是一般學員，門檻是**持有有效 token**，
  不是任何角色。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.invitation.schemas import (
    EmailInviteReq,
    EmailInviteResult,
    InviteAcceptReq,
    InviteAcceptResult,
    InvitePreview,
)
from app.et.invitation.service import EtInvitationService
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

router = APIRouter(prefix="/api/et", tags=["et-invitation"], dependencies=[Depends(get_et_context)])
_service = EtInvitationService()


@router.post(
    "/courses/{course_id}/invitations/preview",
    response_model=InvitePreview,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
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
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
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


@router.post("/invitations/accept", response_model=InviteAcceptResult)
async def accept_invitation(
    req: InviteAcceptReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> InviteAcceptResult:
    """受邀者以邀請連結加入課程（AC 7 / AC 8）。

    已加入者再點同一條連結不重複加入、回 `already_joined=true` 供前端導向學習頁。
    """
    return await _service.accept(db, token=req.token, operator=operator)
