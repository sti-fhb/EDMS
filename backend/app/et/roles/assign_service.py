"""ET 角色 / 受訓單位標籤指派服務（module-callbacks §3；SRVET003）。

供平台 DP 後台「權限管理」經 `EtAssignProvider` 呼叫。比照
`app/dm/roles/assign_service.py`：差異套用、即時生效、同交易寫稽核。

**本轉接層為 `ET_USER_ROLE` / `ET_USER_TAG` 之權威寫入口**，不信任呼叫端輸入，
一律先驗證再寫。

> **範圍界定**：本 issue（#185 Foundation）交付指派本身；**貼標追溯**（新增標籤時
> 自動補加入該標籤所有「已發布且未關閉」課程並寄彙整信）依賴課程 / 選課 / 通知服務，
> 屬 ET Issue #2（US1 T043）與 #8（US8），於此標 TODO。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import AssignmentView
from app.et.catalog.models import EtTag, EtUserTag
from app.et.constants import ALL_ROLES, ROLE_ADMIN
from app.et.roles.models import EtUserRole
from app.services import AuditLogService

logger = logging.getLogger(__name__)

_FUNC_NAME = "ET-ROLES"
_MODULE = "ET"


def _ensure_valid_roles(roles: set[str]) -> None:
    """角色代碼須全屬 ET 三角色（ADMIN / TEACHER / STUDENT）。"""
    invalid = roles - ALL_ROLES
    if invalid:
        raise AppError(status_code=422, detail="指定之角色代碼無效", error_code="ET_ROLE_003")


def _ensure_numeric_tag_ids(groups: set[str]) -> None:
    """群組（受訓單位標籤）以 `ET_TAG.TAG_ID` 字串化傳遞，須為數字。"""
    if any(not g.isdigit() for g in groups):
        raise AppError(status_code=422, detail="指定之受訓單位標籤無效或未啟用", error_code="ET_ROLE_002")


def ensure_not_self_admin_removal(operator_id: str, user_id: str, roles: set[str]) -> None:
    """自我保護：操作者不得取消自己之管理者角色。

    DP 端以 error_code 尾碼 `_ROLE_001` 判別後，統一映射為 `DP_ROLE_002` /
    `DP-MSG-DP06-001` 呈現（見 dp/spec_us7 FR-06）。

    **不檢核「至少 1 名管理者」**——per et/spec.md 設計取捨，該情境極少，
    由 IT 透過 DB 恢復即可。
    """
    if operator_id == user_id and ROLE_ADMIN not in roles:
        raise AppError(status_code=403, detail="無法取消自己的管理者角色", error_code="ET_ROLE_001")


class EtAssignService:
    """ET 角色 / 標籤指派（DP 後台權限管理之寫入實作）。"""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService()

    async def get_users_assignments(self, db: AsyncSession, user_ids: list[str]) -> dict[str, AssignmentView]:
        """批次載入一頁使用者之 ET 角色與標籤現況（避免逐列 N+1）。

        查無指派者回**空集合 View**（非缺 key），供 DP 端一致處理。
        `last_modified_*` 取 `ET_USER_ROLE` / `ET_USER_TAG` 之 `UPDATED_*` 較新者，
        **無 UPDATED_* 時回退至 CREATED_***（比照 DM）——新授予之列尚未被異動過。
        """
        result: dict[str, AssignmentView] = {
            uid: AssignmentView(frozenset(), frozenset(), None, None) for uid in user_ids
        }
        if not user_ids:
            return result

        roles_by_user: dict[str, set[str]] = {uid: set() for uid in user_ids}
        tags_by_user: dict[str, set[str]] = {uid: set() for uid in user_ids}
        last_by_user: dict[str, tuple[str | None, datetime | None]] = {uid: (None, None) for uid in user_ids}

        def _track(uid: str, who: str | None, when: datetime | None) -> None:
            if when is None:
                return
            _, cur_when = last_by_user[uid]
            if cur_when is None or when > cur_when:
                last_by_user[uid] = (who, when)

        role_rows = await db.execute(
            select(
                EtUserRole.user_id,
                EtUserRole.role,
                EtUserRole.updated_user,
                EtUserRole.updated_date,
                EtUserRole.created_user,
                EtUserRole.created_date,
            ).where(
                EtUserRole.user_id.in_(user_ids),
                EtUserRole.is_active.is_(True),
                EtUserRole.deleted == 0,
            )
        )
        for uid, role, upd_user, upd_date, crt_user, crt_date in role_rows:
            roles_by_user[uid].add(role)
            # 回退至 CREATED_*：新授予而從未再異動之列（如 grant_default_student_role
            # 或 bootstrap seed 所建）無 UPDATED_*，否則 DP 後台「最後異動」欄會空白
            _track(uid, upd_user or crt_user, upd_date or crt_date)

        tag_rows = await db.execute(
            select(
                EtUserTag.user_id,
                EtUserTag.tag_id,
                EtUserTag.updated_user,
                EtUserTag.updated_date,
                EtUserTag.created_user,
                EtUserTag.created_date,
            ).where(
                EtUserTag.user_id.in_(user_ids),
                EtUserTag.deleted == 0,
            )
        )
        for uid, tag_id, upd_user, upd_date, crt_user, crt_date in tag_rows:
            tags_by_user[uid].add(str(tag_id))
            _track(uid, upd_user or crt_user, upd_date or crt_date)

        for uid in user_ids:
            who, when = last_by_user[uid]
            result[uid] = AssignmentView(
                roles=frozenset(roles_by_user[uid]),
                groups=frozenset(tags_by_user[uid]),
                last_modified_by=who,
                last_modified_date=when,
            )
        return result

    async def assign(
        self, db: AsyncSession, *, user_id: str, roles: set[str], groups: set[str], operator_id: str
    ) -> None:
        """設定使用者之 ET 角色與受訓單位標籤為目標集合（差異套用、即時生效）。

        Raises:
            AppError: 自我保護（403 `ET_ROLE_001`）、標籤無效 / 未啟用（422 `ET_ROLE_002`）、
                角色代碼無效（422 `ET_ROLE_003`）。
        """
        _ensure_valid_roles(roles)
        _ensure_numeric_tag_ids(groups)
        # 自我保護先於任何寫入
        ensure_not_self_admin_removal(operator_id, user_id, roles)

        current = (await self.get_users_assignments(db, [user_id]))[user_id]
        roles_add, roles_remove = roles - current.roles, current.roles - roles
        tags_add, tags_remove = groups - current.groups, current.groups - groups
        if not (roles_add or roles_remove or tags_add or tags_remove):
            return  # 無實際異動：不寫入、不記稽核

        await self._validate_tags_enabled(db, tags_add)

        for role in sorted(roles_remove):
            await self._set_role(db, user_id, role, active=False, operator_id=operator_id)
        for role in sorted(roles_add):
            await self._set_role(db, user_id, role, active=True, operator_id=operator_id)
        for tag_id in sorted(tags_remove, key=int):
            await self._set_tag(db, user_id, int(tag_id), attached=False, operator_id=operator_id)
        for tag_id in sorted(tags_add, key=int):
            await self._set_tag(db, user_id, int(tag_id), attached=True, operator_id=operator_id)

        await db.flush()

        # TODO(ET Issue #2 / #8)：貼標追溯——新增標籤時補加入該標籤所有「已發布且未關閉」
        # 課程（JOIN_SOURCE=TAG_DEFAULT）並寄彙整信；移除時既有 ET_ENROLLMENT 不變動。
        # 依賴課程 / 選課 / 通知服務，本 Foundation issue 尚未具備。

        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=user_id,
            description="變更 ET 角色 / 受訓單位標籤指派",
            after_value={"roles": sorted(roles), "tags": sorted(groups, key=int)},
        )

    async def _validate_tags_enabled(self, db: AsyncSession, tag_ids: set[str]) -> None:
        """新增之標籤須存在且為啟用中——停用標籤不可**新增**指派（既有指派保留）。"""
        if not tag_ids:
            return
        rows = await db.scalars(
            select(EtTag.tag_id).where(
                EtTag.tag_id.in_([int(t) for t in tag_ids]),
                EtTag.is_active.is_(True),
                EtTag.deleted == 0,
            )
        )
        if {str(t) for t in rows.all()} != tag_ids:
            raise AppError(status_code=422, detail="指定之受訓單位標籤無效或未啟用", error_code="ET_ROLE_002")

    async def _set_role(self, db: AsyncSession, user_id: str, role: str, *, active: bool, operator_id: str) -> None:
        """角色指派 upsert——已有列改 `IS_ACTIVE`（保留稽核欄位），無列則新增。

        以切換旗標而非刪列，避免唯一約束 (USER_ID, ROLE) 阻擋日後重新授予。
        """
        now = datetime.now(timezone.utc)
        existing = await db.scalar(select(EtUserRole).where(EtUserRole.user_id == user_id, EtUserRole.role == role))
        if existing is None:
            if not active:
                return
            db.add(
                EtUserRole(
                    user_id=user_id,
                    role=role,
                    is_active=True,
                    created_user=operator_id,
                    created_date=now,
                    deleted=0,
                )
            )
            return
        existing.is_active = active
        existing.deleted = 0
        existing.updated_user = operator_id
        existing.updated_date = now

    async def _set_tag(self, db: AsyncSession, user_id: str, tag_id: int, *, attached: bool, operator_id: str) -> None:
        """標籤指派 upsert——已有列改 `DELETED`（`ET_USER_TAG` 無 IS_ACTIVE 欄位），無列則新增。"""
        now = datetime.now(timezone.utc)
        existing = await db.scalar(select(EtUserTag).where(EtUserTag.user_id == user_id, EtUserTag.tag_id == tag_id))
        if existing is None:
            if not attached:
                return
            db.add(
                EtUserTag(
                    user_id=user_id,
                    tag_id=tag_id,
                    created_user=operator_id,
                    created_date=now,
                    deleted=0,
                )
            )
            return
        existing.deleted = 0 if attached else 1
        existing.updated_user = operator_id
        existing.updated_date = now
