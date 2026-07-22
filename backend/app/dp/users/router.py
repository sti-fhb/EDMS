"""使用者管理端點（US4 / dp-users）。

授權：依 [sti-backend-modules 暫行授權規則] 僅掛 router-level get_jwt_payload 認證，
寫入型端點注入 get_operator；**不掛 admin 閘**（SA 裁示 Q1=A，待 ET/DM service 就緒於 T049 回歸）。
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_payload
from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import MAX_LIMIT, PagedResponse
from app.dp.users.schemas import UserCreate, UserResponse, UserStatusUpdate, UserUpdate
from app.dp.users.service import UsersService

router = APIRouter(prefix="/api/dp/users", tags=["dp-users"], dependencies=[Depends(get_jwt_payload)])

_service = UsersService()


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


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """管理者代建帳號（初始密碼 + MUST_CHANGE_PWD + 授 ET 學員 + 首筆歷程 + 稽核）。"""
    return await _service.create_user(db, data=data, operator=operator)


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
    """維護基本資料（姓名 / Email 直接生效，不走驗證信）。"""
    return await _service.update_basic(db, user_id=user_id, data=data, operator=operator)
