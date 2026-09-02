"""權限管理（dp-roles）轉接端點（US7）。

DP 後台 ET / DM 共用之角色 / 群組指派入口。DP 為轉接層，經 `RolesService` 呼叫模組 provider。

授權：router-level 掛 `require_any_module_admin()`（#250——需 ET 或 DM 任一模組管理者，
落地 spec_us7「作為 ET 或 DM 管理者」）；**每模組操作再 enforce `is_module_admin`**
（於 service `_require_manageable`），越權 403。兩層並存且職責不同：router 閘管「能否進本頁」，
service 閘管「能否維護該模組」——兼具兩身分者才看得到兩個頁籤。寫入注入 `get_operator`。
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.module_admin import require_any_module_admin
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse
from app.dp.roles.schemas import AssignmentItem, AssignPayload, GroupOption
from app.dp.roles.service import RolesService

router = APIRouter(prefix="/api/dp/roles", tags=["dp-roles"], dependencies=[Depends(require_any_module_admin())])

_service = RolesService()


@router.get("/modules", response_model=list[str])
async def manageable_modules(
    payload: JwtPayload = Depends(get_jwt_payload), db: AsyncSession = Depends(get_db)
) -> list[str]:
    """當前使用者可管理之模組（決定前端顯示哪些頁籤；未具管理權 / 未註冊之模組不出現）。"""
    return await _service.manageable_modules(db, payload.sub)


@router.get("/{module}/assignments", response_model=PagedResponse[AssignmentItem])
async def list_assignments(
    module: str,
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列一頁使用者 + 該模組角色 / 群組現況（越權 403）。"""
    return await _service.list_assignments(
        db, module=module, keyword=keyword, page=page, limit=limit, operator=operator
    )


@router.put("/{module}/assignments/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign(
    module: str,
    user_id: str,
    data: AssignPayload,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """設定使用者於該模組之角色 + 群組（委派模組 provider；自我保護 403、越權 403）。"""
    await _service.assign(db, module=module, user_id=user_id, roles=data.roles, groups=data.groups, operator=operator)


@router.get("/{module}/group-options", response_model=list[GroupOption])
async def group_options(
    module: str,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> list[GroupOption]:
    """該模組群組可選清單（DM＝可見對象，僅列啟用中；越權 403）。"""
    return await _service.group_options(db, module=module, user_id=operator.user_id)
