"""DM 共用存取判定 API。

`GET /api/dm/admin-access`：回是否具 DM_ADMIN，供前端側欄逐項閘（US10 已廢止 / US11 變更歷程 /
US13 KPI 等 admin-only 項共用；語意中性、不綁特定功能）。回布林、非 403——非管理者取得 `false`。
各功能端點自身之 DM_ADMIN 硬閘（擋直連）另在各模組 service 層，與本端點無關。
"""

from fastapi import APIRouter, Depends

from app.dm.access.schemas import AdminAccess, ReviewerAccess
from app.dm.deps import DmContext, get_dm_context
from app.dm.roles.authz import DM_ADMIN, DM_REVIEWER, has_role

router = APIRouter(prefix="/api/dm", tags=["dm-access"])


@router.get("/admin-access", response_model=AdminAccess)
async def admin_access(ctx: DmContext = Depends(get_dm_context)) -> AdminAccess:
    """DM 管理者入口可見性（共用逐項閘）：具 DM_ADMIN → can_access=true。"""
    return AdminAccess(can_access=has_role(ctx.roles, DM_ADMIN))


@router.get("/reviewer-access", response_model=ReviewerAccess)
async def reviewer_access(ctx: DmContext = Depends(get_dm_context)) -> ReviewerAccess:
    """DM 審核者入口可見性（#250）：具 DM_REVIEWER → can_access=true。

    供側欄決定「簽核中心」是否顯示。同 `admin-access` 回布林、非 403——非審核者取得
    false 而不是錯誤；擋直連的硬閘為 `/api/dm/reviews/*` 上的 `get_dm_reviewer_context`。
    """
    return ReviewerAccess(can_access=has_role(ctx.roles, DM_REVIEWER))
