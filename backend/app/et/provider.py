"""ET 指派轉接層 provider（module-callbacks §3 / §3.1；SRVET003 / SRVET004）。

把 ET 之角色 / 受訓單位標籤指派（`EtAssignService`）與受控主檔維護
（`EtCatalogAdapter`）組成單一 provider，註冊進 `module_assign_registry` 供 DP 後台
呼叫。比照 `app/dm/provider.py`。

registry 之 `groups` 對 ET＝受訓單位標籤（`app/core/module_assign.py` 註解已明文預留）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_assign import AssignmentView, ControlledItemView, SetEnabledResult
from app.et.catalog.adapter import EtCatalogAdapter
from app.et.roles.assign_service import EtAssignService


class EtAssignProvider:
    """ET 指派 / 維護轉接層（實作 `ModuleAssignProvider`）。"""

    def __init__(self, assign: EtAssignService | None = None, catalog: EtCatalogAdapter | None = None) -> None:
        self._assign = assign or EtAssignService()
        self._catalog = catalog or EtCatalogAdapter()

    async def get_users_assignments(self, db: AsyncSession, user_ids: list[str]) -> dict[str, AssignmentView]:
        return await self._assign.get_users_assignments(db, user_ids)

    async def assign(
        self, db: AsyncSession, *, user_id: str, roles: set[str], groups: set[str], operator_id: str
    ) -> None:
        await self._assign.assign(db, user_id=user_id, roles=roles, groups=groups, operator_id=operator_id)

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]:
        return await self._catalog.list_controlled(db, kind, enabled_only=enabled_only)

    async def create_controlled(self, db: AsyncSession, kind: str, *, code: str, name: str, operator_id: str) -> None:
        await self._catalog.create_controlled(db, kind, code=code, name=name, operator_id=operator_id)

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        await self._catalog.rename_controlled(db, kind, code=code, new_name=new_name, operator_id=operator_id)

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        return await self._catalog.set_controlled_enabled(db, kind, code=code, enabled=enabled, operator_id=operator_id)

    async def list_audiences(self, db: AsyncSession, *, enabled_only: bool = True) -> list[ControlledItemView]:
        return await self._catalog.list_audiences(db, enabled_only=enabled_only)
