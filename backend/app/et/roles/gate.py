"""ET 模組角色判定閘 checker（module-callbacks §1 / §4；SRVET001 / SRVET005）。

供平台 DP 經 `module_role_gate`（入口頁 / 側欄）與 `module_admin_gate`（後台端點過濾）
呼叫，比照 `app/dm/roles/gate.py`：

- `et_has_any_role`（§4 / SRVET005）：查 `ET_USER_ROLE` 是否具任一 ET 角色。
- `et_is_module_admin`（§1 / SRVET001）：查是否具 `ADMIN`。

兩者以呼叫方 db session 查詢、回純布林。**閘對執行期例外一律 fail-closed**
（由 `app/core/module_admin.py` / `module_roles.py` 統一處理，此處不自行吞例外）。

> ⚠️ `et_is_module_admin` 亦是 dp-roles「誰能指派 ET 角色」的判定來源——`ET_USER_ROLE`
> 為空時無人是管理者，形成「要當管理者才能指派管理者」之死結。首位管理者由 ET 角色
> seed 解開（#185 SA Q1 裁示）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.deps import load_et_roles
from app.et.roles.authz import ET_ADMIN, has_any_et_role, has_role


async def et_has_any_role(db: AsyncSession, user_id: str) -> bool:
    """user_id 是否具任一 ET 角色（§4）。"""
    return has_any_et_role(await load_et_roles(db, user_id))


async def et_is_module_admin(db: AsyncSession, user_id: str) -> bool:
    """user_id 是否為 ET 管理者（§1）。"""
    return has_role(await load_et_roles(db, user_id), ET_ADMIN)
