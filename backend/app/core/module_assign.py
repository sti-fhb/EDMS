"""模組角色 / 可見對象指派轉接層 registry（US1，module-callbacks §3 / §3.1）。

DP 後台「權限管理」（§3 角色 / 群組指派）與「系統參數與清單」（§3.1 受控主檔維護）經本
registry 取得各模組 provider 後呼叫——ET / DM 於啟動期註冊，未註冊回 None（fail-closed，
DP 端視為該模組無可指派項 / 無可維護清單）。比照 `module_role_gate` 之聚合閘機制。

群組（`groups`）為模組各自語意之抽象：DM＝可見對象（AUDIENCE 標籤），ET＝受訓單位標籤。
provider 內部以各自 model 落地，registry 不涉模組表。
"""

import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssignmentView:
    """單一使用者於某模組之現況（§3 批次載入用）。"""

    roles: frozenset[str]
    groups: frozenset[str]  # DM＝AUDIENCE 標籤 TAG_ID；ET＝受訓單位標籤
    last_modified_by: str | None
    last_modified_date: datetime | None


@dataclass(frozen=True)
class ControlledItemView:
    """受控主檔項（§3.1；DM＝分類 / func / 標籤）。"""

    kind: str  # 'CATEGORY' | 'FUNC' | 'TAG'
    code: str  # CATEGORY_CODE / FUNC_CODE；TAG 用 TAG_ID（字串化）
    name: str
    is_builtin: bool
    is_enabled: bool
    group_type: str | None = None  # 僅 TAG：'AUDIENCE' | 'RETRIEVAL'
    tag_group_code: str | None = None  # 僅 TAG


@dataclass(frozen=True)
class SetEnabledResult:
    """啟停結果；AUDIENCE 標籤停用（soft-retire）帶受影響數，其餘為 None。"""

    affected_docs: int | None = None
    affected_viewers: int | None = None


class ModuleAssignProvider(Protocol):
    """模組指派轉接層 provider（§3 角色 / 群組指派 + §3.1 受控主檔維護）。

    以呼叫方 db session 執行、只 flush 不 commit；指派 / 維護異動由 provider 於同交易寫稽核。
    """

    async def get_users_assignments(self, db: AsyncSession, user_ids: list[str]) -> dict[str, AssignmentView]: ...

    async def assign(
        self, db: AsyncSession, *, user_id: str, roles: set[str], groups: set[str], operator_id: str
    ) -> None: ...

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]: ...

    async def create_controlled(
        self, db: AsyncSession, kind: str, *, code: str, name: str, operator_id: str
    ) -> None: ...

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None: ...

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> Awaitable[SetEnabledResult] | SetEnabledResult: ...


class ModuleAssignRegistry:
    """聚合各模組指派轉接層 provider（stub 可注入替換）。"""

    def __init__(self) -> None:
        self._providers: dict[str, ModuleAssignProvider] = {}

    def register(self, module: str, provider: ModuleAssignProvider) -> None:
        """註冊 / 替換某模組 provider（僅限啟動期與測試呼叫，禁置於請求 handler）。"""
        if module in self._providers:
            logger.warning("模組指派 provider 被覆蓋 module=%s", module)
        self._providers[module] = provider

    def unregister(self, module: str) -> None:
        """移除某模組 provider（未註冊為 no-op）。"""
        self._providers.pop(module, None)

    def get(self, module: str) -> ModuleAssignProvider | None:
        """取某模組 provider；未註冊回 None（呼叫端 fail-closed 處理）。"""
        return self._providers.get(module)


# 全域單例：各模組啟動時 register 自己的 provider，DP 後台經此聚合。
module_assign_registry = ModuleAssignRegistry()
