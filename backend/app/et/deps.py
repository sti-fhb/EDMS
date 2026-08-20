"""ET 模組存取閘 Dependency（T025）。

ET 全模組端點的統一進入閘（FastAPI `Depends`，非 ASGI middleware），比照
`app/dm/deps.py`：

- **認證**：重用平台 `get_jwt_payload`（DP 對稱 JWT + 每請求查 DP_USER 狀態）；
  缺 token / 竄改 / 停用 / 鎖定由平台先擋（401 / 403）。
- **授權**：查 `ET_USER_ROLE`，要求呼叫者至少具備一個 ET 角色；無任何 ET 角色 →
  403 `ET_AUTH_001`（已登入但未獲教育訓練權限）。

細粒度角色檢核（管理者 / 教師 / 學員）由各端點以 `app/et/roles/authz` 之 `has_role`
等進一步把關；本閘只負責「是否為 ET 使用者」的粗粒度准入，並把角色集帶給下游。

> 註：ET 學員角色於帳號建立當下即自動授予（SRVET002），故一般使用者恆可通過本閘；
> 存量帳號之學員角色由 ET 角色 seed 回填（#185 SA Q1 裁示）。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.exceptions import AppError
from app.et.roles.models import EtUserRole


@dataclass(frozen=True)
class EtContext:
    """ET 請求情境：操作者 USER_ID 與其 ET 角色集（供端點細粒度授權）。"""

    user_id: str
    roles: frozenset[str]


async def load_et_roles(db: AsyncSession, user_id: str) -> frozenset[str]:
    """查使用者於 `ET_USER_ROLE` 之有效角色集。

    僅取 `IS_ACTIVE=true` 且未軟刪除者——停用之角色指派不得生效。
    """
    rows = await db.scalars(
        select(EtUserRole.role).where(
            EtUserRole.user_id == user_id,
            EtUserRole.is_active.is_(True),
            EtUserRole.deleted == 0,
        )
    )
    return frozenset(rows.all())


async def get_et_context(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> EtContext:
    """ET 端點統一存取閘：通過平台認證且具備任一 ET 角色才放行。

    Raises:
        AppError: 已認證但無任何 ET 角色（403 `ET_AUTH_001`）。
    """
    roles = await load_et_roles(db, payload.sub)
    if not roles:
        raise AppError(status_code=403, detail="需要教育訓練模組權限", error_code="ET_AUTH_001")
    return EtContext(user_id=payload.sub, roles=roles)


def require_et_roles(*required: str) -> Callable[..., Awaitable[EtContext]]:
    """端點層授權 dependency factory——**宣告即生效**，不必記得在 service 層自行比對。

    `get_et_context` 只驗「是否為 ET 使用者」，而 ET 學員角色於帳號建立當下即自動授予、
    存量帳號亦由 bootstrap seed 回填——**實務上任何登入者都持有至少一個 ET 角色**，
    故單掛 `get_et_context` 幾乎等同「已登入」，不構成授權控制。

    若端點需要特定角色（如管理者專屬、教師專屬），請改掛本工廠：

        @router.post("/courses", dependencies=[Depends(require_et_roles(ET_ADMIN, ET_TEACHER))])

    這樣「漏掉授權」會表現為「沒掛 dependency」（顯眼），而非「掛了但沒比對」（隱形）。

    Raises:
        AppError: 不具任一 required 角色（403 `ET_AUTH_001`）。
    """

    required_set = frozenset(required)

    async def _dep(ctx: EtContext = Depends(get_et_context)) -> EtContext:
        if not (ctx.roles & required_set):
            raise AppError(status_code=403, detail="需要教育訓練模組權限", error_code="ET_AUTH_001")
        return ctx

    return _dep
