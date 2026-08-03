"""使用者管理端點（US4 / dp-users）。

授權：依 [sti-backend-modules 暫行授權規則] 僅掛 router-level get_jwt_payload 認證，
寫入型端點注入 get_operator；**不掛 admin 閘**（SA 裁示 Q1=A，待 ET/DM service 就緒於 T049 回歸）。
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_payload
from app.core.config import settings
from app.core.cooldown import VerifySendCooldown
from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import MAX_LIMIT, PagedResponse
from app.dp.users.schemas import InviteResponse, UserCreate, UserResponse, UserStatusUpdate, UserUpdate
from app.dp.users.service import UsersService

router = APIRouter(prefix="/api/dp/users", tags=["dp-users"], dependencies=[Depends(get_jwt_payload)])

_service = UsersService()

# 邀請端點加固（#72）：對「單筆邀請（res_id）」重寄設冷卻，防對同一受邀信箱短時間反覆轟炸。
# 刻意**不設操作者總量限流**（PO 決策）：管理者一次為多位不同使用者建帳號屬正常作業，
# 不應以總量節流；「同帳號防轟炸」由「建立時同 Email 重複 → 409」＋本冷卻共同達成。
# 冷卻秒數走 config（deploy 可調、免 migration，見 config.INVITE_RESEND_COOLDOWN_SEC）。
_invite_resend_cooldown = VerifySendCooldown()


@router.get("", response_model=PagedResponse[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, max_length=255),
    account_status: Optional[Literal["active", "disabled", "locked"]] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
):
    """查詢使用者清單（姓名 / Email 關鍵字 + 狀態篩選，後端分頁）。"""
    return await _service.list_users(db, keyword=q, status=account_status, page=page, limit=limit)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> dict[str, str]:
    """管理者建立帳號＝寄邀請信（#67）：寫待邀請列 + 寄 ACCOUNT_INVITE 信；不建 DP_USER。

    不設總量限流（#72 PO 決策）：批次為多人建帳號屬正常；對同一 Email 重複建立由服務層 409 擋下。
    """
    await _service.create_user(db, data=data, operator=operator)
    return {"message": "邀請信已寄出，使用者需經連結設定密碼後啟用"}


@router.get("/invites", response_model=PagedResponse[InviteResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
):
    """查詢待啟用邀請清單（ADMIN_INVITE，姓名 / Email 關鍵字，後端分頁）。"""
    return await _service.list_invites(db, keyword=q, page=page, limit=limit)


@router.post("/invites/{res_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_invite(
    res_id: str,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> dict[str, object]:
    """重寄邀請（作廢舊 token、產新並重寄）。

    對「單筆邀請 res_id」冷卻（#72）：check 前置（冷卻中拋 429 帶 retry_after）、record 於服務
    成功後（重寄失敗如 404 不誤觸冷卻），防對同一受邀信箱短時間反覆轟炸。
    成功回應帶 retry_after（＝完整冷卻秒數）供前端起算倒數。
    """
    cooldown_key = f"invite:resend:{res_id}"
    _invite_resend_cooldown.check(cooldown_key, settings.INVITE_RESEND_COOLDOWN_SEC)
    await _service.resend_invite(db, res_id=res_id, operator=operator)
    _invite_resend_cooldown.record(cooldown_key)
    return {"message": "邀請信已重寄", "retry_after": settings.INVITE_RESEND_COOLDOWN_SEC}


@router.delete("/invites/{res_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(
    res_id: str,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> None:
    """取消邀請（刪除待邀請列）。"""
    await _service.cancel_invite(db, res_id=res_id, operator=operator)


@router.patch("/{user_id}/status", response_model=UserResponse)
async def set_user_status(
    user_id: str,
    data: UserStatusUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """停用 / 啟用帳號（停用有自我保護）。"""
    return await _service.set_status(db, user_id=user_id, action=data.action, operator=operator)


@router.patch("/{user_id}/unlock", response_model=UserResponse)
async def unlock_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """解鎖帳號（登入失敗計數歸零 + 解除鎖定）。"""
    return await _service.unlock(db, user_id=user_id, operator=operator)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_basic(
    user_id: str,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """維護基本資料（#67：僅可改姓名；Email 為登入帳號、唯讀不可代改）。"""
    return await _service.update_basic(db, user_id=user_id, data=data, operator=operator)
