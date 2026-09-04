"""DM 模組存取閘 Dependency（T014）。

DM 全模組端點的統一進入閘（FastAPI `Depends`，非 ASGI middleware）：

- **認證**：重用平台 `get_jwt_payload`（DP 對稱 JWT + 每請求查 DP_USER 狀態）；缺 token /
  竄改 / 停用 / 鎖定由平台先擋（401 / 403）。
- **授權**：查 `DM_USER_ROLE`，要求呼叫者至少具備一個 DM 角色；無任何 DM 角色 → 403
  `DM_AUTH_001`（已登入但未獲文件管理權限）。

細粒度角色檢核（編輯 / 審核 / 管理）由各端點以 `dm.roles.authz` 之 `has_role` 進一步把關；
本閘只負責「是否為 DM 使用者」的粗粒度准入，並把角色集帶給下游（含可見範圍過濾用）。
"""

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.exceptions import AppError
from app.dm.roles.authz import DM_REVIEWER, has_role
from app.dm.roles.models import DmUserRole


@dataclass(frozen=True)
class DmContext:
    """DM 請求情境：操作者 USER_ID 與其 DM 角色集（供端點細粒度授權 / 可見範圍過濾）。"""

    user_id: str
    roles: frozenset[str]


async def load_dm_roles(db: AsyncSession, user_id: str) -> frozenset[str]:
    """查使用者於 DM_USER_ROLE 之有效角色集（未刪除）。"""
    rows = await db.scalars(select(DmUserRole.role_code).where(DmUserRole.user_id == user_id, DmUserRole.deleted == 0))
    return frozenset(rows.all())


async def get_dm_context(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> DmContext:
    """DM 端點統一存取閘：通過平台認證且具備任一 DM 角色才放行。

    Raises:
        AppError: 已認證但無任何 DM 角色（403 DM_AUTH_001）。
    """
    roles = await load_dm_roles(db, payload.sub)
    if not roles:
        raise AppError(status_code=403, detail="需要文件管理模組權限", error_code="DM_AUTH_001")
    return DmContext(user_id=payload.sub, roles=roles)


async def get_dm_reviewer_context(ctx: DmContext = Depends(get_dm_context)) -> DmContext:
    """簽核中心入口閘（#250）：於模組存取閘之上再要求 `DM_REVIEWER`。

    嚴格只認審核者——**僅具 `DM_ADMIN` 者亦不放行**（SA #250 Q3=A：管理者管設定、
    審核者管簽核；管理者需代審時自行加勾審核者角色）。原本非審核者可進入並取得空清單
    （清單依 `assigned_reviewer=登入者` 過濾），入口看得到卻永遠空白，語意不一致。

    本閘為**粗粒度入口**判定；「是否為該筆送審的指定審核者」仍由 `center_service` 以
    `DM_REVIEW_005` 逐筆把關，兩層並存、職責不同。

    Raises:
        AppError: 具 DM 角色但無 DM_REVIEWER（403 DM_AUTH_004）。
    """
    if not has_role(ctx.roles, DM_REVIEWER):
        raise AppError(status_code=403, detail="需要文件審核者權限", error_code="DM_AUTH_004")
    return ctx
