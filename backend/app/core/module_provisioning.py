"""模組預設角色授予閘（T026，module-callbacks §2）。

帳號建立當下（US2 自助註冊 / US4 代建）由 DP 呼叫各模組的預設角色授予介面。
ET 提供 `grant_default_student_role`（寫 ET_USER_ROLE 學員 + 標籤未指派、冪等）；
ET 於啟動時把 checker 註冊進來（同 T017 / module_roles 判定閘機制），測試可注入 stub 替換。

與 has_any_role（讀取、fail-closed False）不同：授予失敗**不得**被吞掉——
使用者少了預設角色即為壞帳號，故已註冊模組的 checker 若拋例外一律向上傳播，
讓呼叫方（註冊 / 代建）整筆交易回滾。**未註冊**模組則視為 no-op（ET 尚未接線前的
stub 先行；註冊仍可完成，真正授予待模組就緒後於 T047 回歸）。
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# checker 由業務模組提供：以呼叫方 db session 於同交易內寫入該模組預設角色。
# module-callbacks §2 簽章為 (user_id)，此為同進程落地版（多帶 db 供同交易寫入）。
GrantDefaultRoleChecker = Callable[[AsyncSession, str], Awaitable[None]]


class ModuleProvisioningGate:
    """聚合各模組「帳號建立時預設角色授予」的閘（stub 可注入替換）。"""

    def __init__(self) -> None:
        self._granters: dict[str, GrantDefaultRoleChecker] = {}

    def register(self, module: str, granter: GrantDefaultRoleChecker) -> None:
        """註冊 / 替換某模組的預設角色授予 granter（僅限啟動期與測試呼叫，禁置於請求 handler）。"""
        if module in self._granters:
            logger.warning("模組預設角色 granter 被覆蓋 module=%s", module)
        self._granters[module] = granter

    def unregister(self, module: str) -> None:
        """移除某模組 granter（未註冊為 no-op）。"""
        self._granters.pop(module, None)

    async def grant_default_role(self, module: str, user_id: str, db: AsyncSession) -> None:
        """於同交易內授予 user_id 在 module 的預設角色。

        模組未註冊 granter → no-op（stub 先行，註冊仍可完成）；
        已註冊 granter 執行拋例外 → **向上傳播**（授予失敗須讓整筆帳號建立交易回滾）。
        """
        granter = self._granters.get(module)
        if granter is None:
            logger.info("模組 %s 未註冊預設角色 granter，跳過授予（stub 先行）", module)
            return
        await granter(db, user_id)


# 全域單例：各模組啟動時 register 自己的授予介面，DP 帳號建立時經此授予。
module_provisioning_gate = ModuleProvisioningGate()
