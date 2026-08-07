"""DM 模組角色判定閘 checker（US1，module-callbacks §1 / §4）。

供平台 DP 經 `module_role_gate`（入口頁 / 側欄）與 `module_admin_gate`（後台端點過濾）呼叫：
- `dm_has_any_role`（§4）：查 `DM_USER_ROLE` 是否具任一 DM 角色。
- `dm_is_module_admin`（§1）：查是否具 `DM_ADMIN`。

兩者以呼叫方 db session 查詢，回純布林（閘對執行期例外一律 fail-closed）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.deps import load_dm_roles
from app.dm.roles.authz import DM_ADMIN, has_any_dm_role, has_role


async def dm_has_any_role(db: AsyncSession, user_id: str) -> bool:
    """user_id 是否具任一 DM 角色（§4）。"""
    return has_any_dm_role(await load_dm_roles(db, user_id))


async def dm_is_module_admin(db: AsyncSession, user_id: str) -> bool:
    """user_id 是否為 DM 管理者（§1）。"""
    return has_role(await load_dm_roles(db, user_id), DM_ADMIN)
