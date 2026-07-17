"""模組角色判定閘（T025，module-callbacks §4）。

入口頁據各模組 has_any_role 決定卡片狀態：具任一角色＝可進入，無＝未開通。
ET / DM 於啟動時把各自 has_any_role checker 註冊進來（同 T017 判定閘機制）；
未註冊模組一律 fail-closed（回 False）＝未開通，測試可注入 stub 替換。
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# checker 由業務模組提供：以呼叫方 db session 查各自角色表，回操作者是否具該模組任一角色。
# module-callbacks §4 簽章為 (user_id)，此為同進程落地版（多帶 db 供查詢）。
ModuleRoleChecker = Callable[[AsyncSession, str], Awaitable[bool]]


class ModuleRoleGate:
    """聚合各模組 has_any_role 的判定閘（stub 可注入替換）。"""

    def __init__(self) -> None:
        self._checkers: dict[str, ModuleRoleChecker] = {}

    def register(self, module: str, checker: ModuleRoleChecker) -> None:
        """註冊 / 替換某模組的 has_any_role checker（僅限啟動期與測試呼叫，禁置於請求 handler）。"""
        if module in self._checkers:
            logger.warning("模組角色 checker 被覆蓋 module=%s", module)
        self._checkers[module] = checker

    def unregister(self, module: str) -> None:
        """移除某模組 checker（未註冊為 no-op）；移除後該模組回 fail-closed。"""
        self._checkers.pop(module, None)

    async def has_any_role(self, module: str, user_id: str, db: AsyncSession) -> bool:
        """判定 user_id 於 module 是否具任一角色。

        模組未註冊 checker、或 checker 執行期拋例外，一律回 False（fail-closed）＝未開通——
        checker 為模組提供之外部 callable，其失敗不得升級為未開通誤放行或未處理的 500。
        """
        checker = self._checkers.get(module)
        if checker is None:
            return False
        try:
            result = await checker(db, user_id)
        except Exception:
            logger.exception("模組角色判定 checker 執行失敗 module=%s", module)
            return False
        # 嚴格布林收斂：只在明確 True 放行
        return result is True


# 全域單例：各模組啟動時 register 自己的 has_any_role，DP 入口頁經此聚合。
module_role_gate = ModuleRoleGate()
