"""模組管理者判定閘（T017）。

JWT 不含角色（research §4）；DP 後台端點每請求經本閘呼叫各模組提供的 is_module_admin
判定操作者管理者身分（module-callbacks §1）。ET / DM 於啟動時把各自 checker 註冊進來，
DP 經閘呼叫——core 為中立處，雙方皆可 import 而不互相耦合內部（sti-backend-boundaries）。

ET / DM 尚未實作，未註冊模組一律 fail-closed（回 False）；測試可注入 stub 替換。
"""

import logging
from collections.abc import Awaitable, Callable, Iterable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

# checker 由業務模組提供：以呼叫方 db session 查各自 ET_/DM_USER_ROLE，回操作者是否為該模組管理者。
# module-callbacks §1 簽章為 (user_id)，此為同進程落地版（多帶 db 供查詢）。
ModuleAdminChecker = Callable[[AsyncSession, str], Awaitable[bool]]


class ModuleAdminGate:
    """聚合各模組 is_module_admin 的判定閘（stub 可注入替換）。"""

    def __init__(self) -> None:
        self._checkers: dict[str, ModuleAdminChecker] = {}

    def register(self, module: str, checker: ModuleAdminChecker) -> None:
        """註冊 / 替換某模組的管理者判定 checker（僅限啟動期與測試呼叫，禁置於請求 handler）。"""
        if module in self._checkers:
            # 啟動期非預期的重複註冊（如較寬鬆 checker 蓋掉正式版）應可被觀測
            logger.warning("模組管理者 checker 被覆蓋 module=%s", module)
        self._checkers[module] = checker

    def unregister(self, module: str) -> None:
        """移除某模組 checker（未註冊為 no-op）；移除後該模組回 fail-closed。"""
        self._checkers.pop(module, None)

    async def is_module_admin(self, module: str, user_id: str, db: AsyncSession) -> bool:
        """判定 user_id 是否為 module 的管理者。

        模組未註冊 checker、或 checker 執行期拋例外，一律回 False（fail-closed）——
        checker 為模組提供之外部 callable，其失敗不得升級為權限繞過或未處理的 500。
        """
        checker = self._checkers.get(module)
        if checker is None:
            return False
        try:
            result = await checker(db, user_id)
        except Exception:
            # 只記 module，不記 user_id（避免 PII 入 log）；fail-closed 視同非管理者
            logger.exception("模組管理者判定 checker 執行失敗 module=%s", module)
            return False
        # 嚴格布林收斂：只在明確 True 放行；truthy 非 bool（如角色清單 / int）一律 fail-closed
        return result is True

    async def is_any_module_admin(self, modules: Iterable[str], user_id: str, db: AsyncSession) -> bool:
        """user_id 是否為 modules 中**任一**模組的管理者（#250）。

        DP 後台六項功能之操作者依 spec（us4 / us5 / us7 / us9 / us10 / us11）皆為
        「ET 或 DM 管理者」，故以 or 聚合。逐一委派 `is_module_admin`，因此未註冊模組與
        checker 例外同樣 fail-closed，且單一模組失敗不影響其他模組的判定。

        Args:
            modules: 模組代碼集合（如 ("ET", "DM")）；空集合一律回 False。
            user_id: 操作者 USER_ID。
            db: DB session（傳給各模組 checker）。

        Returns:
            任一模組為管理者回 True；全否 / 空集合回 False。
        """
        for module in modules:
            if await self.is_module_admin(module, user_id, db):
                return True
        return False


# 全域單例：各模組啟動時 register 自己的 checker，DP 端點經此判定。
module_admin_gate = ModuleAdminGate()


def require_module_admin(module: str) -> Callable[..., Awaitable[JwtPayload]]:
    """產生「要求為指定模組管理者」的 FastAPI dependency。

    先經 get_jwt_payload 完成認證（含 DP_USER 狀態檢查），再經閘判定管理者身分；
    非管理者（含模組未接線）拋 403 DP_AUTH_006。

    Args:
        module: 模組代碼（如 "ET" / "DM"）。

    Returns:
        回傳 JwtPayload 的 async dependency。

    Raises:
        AppError: 非該模組管理者（403 / DP_AUTH_006）；認證失敗由 get_jwt_payload 拋（401）。
    """

    async def _dependency(
        payload: JwtPayload = Depends(get_jwt_payload),
        db: AsyncSession = Depends(get_db),
    ) -> JwtPayload:
        if not await module_admin_gate.is_module_admin(module, payload.sub, db):
            raise AppError(status_code=403, detail="需要模組管理者權限", error_code="DP_AUTH_006")
        return payload

    return _dependency


# DP 後台之預設門檻模組：spec_us4 / us5 / us7 / us9 / us10 / us11 皆定義操作者為「ET 或 DM 管理者」
_BACKOFFICE_MODULES: tuple[str, ...] = ("ET", "DM")


def require_any_module_admin(modules: Iterable[str] = _BACKOFFICE_MODULES) -> Callable[..., Awaitable[JwtPayload]]:
    """產生「要求為任一指定模組管理者」的 FastAPI dependency（#250）。

    供 DP 後台各 router 掛於 router-level，取代原先僅認證的 `get_jwt_payload`——
    DP 後台六項功能（使用者管理 / 系統參數 / 通知範本 / 權限管理 / 操作記錄 / 排程總覽）
    之操作者於 spec 皆為「ET 或 DM 管理者」，此前實作只驗認證、授權未落地。

    **不以角色名稱字串判斷**：一律經 `module_admin_gate` 委派各模組 checker
    （`.claude/rules/sti-backend-boundaries.md`——DP 不得認識模組角色碼）。

    Args:
        modules: 門檻模組集合，預設 ET + DM。

    Returns:
        回傳 JwtPayload 的 async dependency。

    Raises:
        AppError: 非任一模組之管理者（403 DP_AUTH_006）；認證失敗由 get_jwt_payload 拋（401）。
    """

    # 固化成 tuple：`modules` 若為一次性 iterator（generator / iter(...)），closure 會在第一個
    # 請求耗盡它，之後每個請求都看到空集合 → 整個 router 恆 403。方向雖 fail-closed，但無訊號、難排查。
    gate_modules = tuple(modules)

    async def _dependency(
        payload: JwtPayload = Depends(get_jwt_payload),
        db: AsyncSession = Depends(get_db),
    ) -> JwtPayload:
        if not await module_admin_gate.is_any_module_admin(gate_modules, payload.sub, db):
            raise AppError(status_code=403, detail="需要模組管理者權限", error_code="DP_AUTH_006")
        return payload

    return _dependency
