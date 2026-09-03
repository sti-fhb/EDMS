"""權限管理（dp-roles）轉接層服務（US7）。

DP 為**轉接層**：經 `module_assign_registry` 呼叫各模組 provider 讀 / 寫角色與群組指派、
經 `module_admin_gate` 做模組過濾（越權 403）。DP **不自持**角色 / 指派資料、不做全域 RBAC、
不定義角色能力；自我保護 / 標籤值檢核 / 稽核皆在模組 provider（module-callbacks §3）。

模組過濾採 SA Q1=A（授權頁特例）：每次操作 enforce `is_module_admin`（非沿用 #5/#6 暫行只認證），
因本頁為提權入口且 `is_module_admin` 已就緒（DM 已註冊）。未註冊 provider 之模組 fail-closed。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.module_assign import ModuleAssignProvider, module_assign_registry
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.roles.schemas import AssignmentItem, GroupOption
from app.dp.users.account_status import is_account_usable
from app.dp.users.service import UsersService


class RolesService:
    """權限管理轉接層（查可管理模組 / 列現況 / 指派 / 群組選項）。"""

    def __init__(self, users: UsersService | None = None) -> None:
        self._users = users or UsersService()

    async def manageable_modules(self, db: AsyncSession, user_id: str) -> list[str]:
        """當前使用者可管理之模組：已註冊 provider 且其為該模組管理者（未註冊模組不出現）。"""
        result: list[str] = []
        for module in module_assign_registry.registered_modules():
            if await module_admin_gate.is_module_admin(module, user_id, db):
                result.append(module)
        return result

    async def list_assignments(
        self, db: AsyncSession, *, module: str, keyword: str | None, page: int, limit: int, operator: OperatorInfo
    ) -> dict:
        """列一頁使用者 + 該模組角色 / 群組現況（重用 dp-users 查詢 + provider 批次載入）。"""
        provider = await self._require_manageable(db, module, operator.user_id)
        users = await self._users.list_users(db, keyword=keyword, status=None, page=page, limit=limit)
        rows = users["data"]  # PaginatedResult 為 TypedDict
        user_ids = [u.user_id for u in rows]
        views = await provider.get_users_assignments(db, user_ids) if user_ids else {}
        # 最後異動者 USER_ID → 顯示名（姓名 / email），供畫面顯示人名而非原始 ID（與 dp-audit 對象解析同慣例）
        modifier_ids = {v.last_modified_by for v in views.values() if v.last_modified_by}
        name_by_id = await self._users.resolve_display_names(db, modifier_ids)
        items = [
            AssignmentItem(
                user_id=u.user_id,
                user_name=u.user_name,
                email=u.email,
                status=u.status,
                locked_until=u.locked_until,
                roles=sorted(views[u.user_id].roles) if u.user_id in views else [],
                groups=sorted(views[u.user_id].groups) if u.user_id in views else [],
                last_modified_by=views[u.user_id].last_modified_by if u.user_id in views else None,
                last_modified_by_name=(
                    name_by_id.get(views[u.user_id].last_modified_by) if u.user_id in views else None
                ),
                last_modified_date=views[u.user_id].last_modified_date if u.user_id in views else None,
            )
            for u in rows
        ]
        return {"data": items, "meta": users["meta"]}

    async def assign(
        self,
        db: AsyncSession,
        *,
        module: str,
        user_id: str,
        roles: list[str],
        groups: list[str],
        operator: OperatorInfo,
    ) -> None:
        """指派角色 / 群組（委派模組 provider）；自我保護（模組 403）統一映射為 DP_ROLE_002。

        Raises:
            AppError: 對停用 / 鎖定中帳號**新增**權限（403 DP_ROLE_004，純撤權不擋）；
                非本模組管理者（403 DP_ROLE_001）；模組自我保護（403 DP_ROLE_002）。
        """
        provider = await self._require_manageable(db, module, operator.user_id)
        await self._require_grantable_target(db, provider, user_id, roles=roles, groups=groups)
        try:
            await provider.assign(
                db, user_id=user_id, roles=set(roles), groups=set(groups), operator_id=operator.user_id
            )
        except AppError as exc:
            # FR-DP-US7-06：模組自我保護統一映射為 DP 訊息。以 error_code 慣例 `{MODULE}_ROLE_001`
            # 判別（非僅 status 403），避免日後模組於 assign 因其他理由拋 403 時被誤映射。
            if (exc.error_code or "").endswith("_ROLE_001"):
                raise AppError(status_code=403, detail="無法取消自己的管理者角色", error_code="DP_ROLE_002") from exc
            raise

    async def group_options(self, db: AsyncSession, *, module: str, user_id: str) -> list[GroupOption]:
        """該模組之群組可選清單（DM＝可見對象；僅列啟用中）。"""
        provider = await self._require_manageable(db, module, user_id)
        audiences = await provider.list_audiences(db)
        return [GroupOption(code=a.code, name=a.name) for a in audiences]

    async def _require_grantable_target(
        self,
        db: AsyncSession,
        provider: ModuleAssignProvider,
        user_id: str,
        *,
        roles: list[str],
        groups: list[str],
    ) -> None:
        """停用 / 鎖定中的帳號只可**撤權**、不可新增權限（#250）。

        已登不進系統的帳號不該取得新權限；但 `assign` 為**整組目標集覆寫**，若一律擋下，
        離職 / 疑遭盜用的帳號就再也無法降權——權限凍結在原狀，日後重新啟用時原封不動復活、
        不經重新核可，牴觸最小權限原則（Security Review MEDIUM-3）。故只擋提權：
        目標集為現況之子集（純撤除）一律放行，超出現況才視為新增而拒絕。

        **查無 DP_USER 者不擋**：對尚未建帳號的 USER_ID 指派為既有允許行為
        （模組角色表無 FK 至 `DP_USER`），本 issue 不改變該行為。軟刪除之帳號同樣回 None
        （`get_by_id` 濾 `DELETED=0`）故一併放行——目前 DP 無「刪除既有帳號」入口
        （離職走 DISABLED），若日後新增則需重新檢視此分支語意。

        Raises:
            AppError: 對停用 / 鎖定中帳號新增角色或群組（403 DP_ROLE_004）。
        """
        account = await self._users.get_account_status(db, user_id)
        if account is None:
            return
        if is_account_usable(status=account.status, locked_until=account.locked_until, now=utcnow()):
            return
        current = (await provider.get_users_assignments(db, [user_id])).get(user_id)
        current_roles = set(current.roles) if current else set()
        current_groups = set(current.groups) if current else set()
        if set(roles) <= current_roles and set(groups) <= current_groups:
            return  # 純撤權（目標集未超出現況）
        raise AppError(status_code=403, detail="此帳號已停用或鎖定，無法新增權限", error_code="DP_ROLE_004")

    async def _require_manageable(self, db: AsyncSession, module: str, user_id: str) -> ModuleAssignProvider:
        """模組過濾閘：未註冊 provider → 404 DP_ROLE_003；非該模組管理者 → 403 DP_ROLE_001（越權，ROLES-003 呈現）。"""
        provider = module_assign_registry.get(module)
        if provider is None:
            raise AppError(status_code=404, detail="查無此模組或尚未提供角色管理", error_code="DP_ROLE_003")
        if not await module_admin_gate.is_module_admin(module, user_id, db):
            raise AppError(status_code=403, detail="無權限維護此模組之角色指派", error_code="DP_ROLE_001")
        return provider
