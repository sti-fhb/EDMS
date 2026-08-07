"""DM 角色 / 可見對象指派服務（US1，module-callbacks §3）。

供 DP 後台「權限管理」經轉接層呼叫：批次載入使用者現況、指派 / 取消 DM 四角色與可見對象授權。

- 角色現況存 `DM_USER_ROLE`（軟刪除；撤銷＝DELETED=1，再授予＝復用同列避開唯一約束），
  每次 GRANT / REVOKE 另寫 append-only `DM_USER_ROLE_LOG`。
- 可見對象授權存 `DM_USER_TAG`（同軟刪除復用機制）；異動以 `UPDATED_*`（最後異動）+ 稽核記錄，
  data-model 無專屬 tag log 表。
- 自我保護：operator 取消自己之 `DM_ADMIN` → `DM_ROLE_001`；不檢核「至少 1 名管理者」。
- 可見對象值 MUST 屬 `DM_TAG`（AUDIENCE 組、`IS_ENABLED=true`）；否則 `DM_ROLE_002`。
- 指派異動於**同交易**呼叫 SRVDP003（`MODULE=DM`）寫稽核。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import AssignmentView
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.roles.authz import ensure_not_self_admin_removal
from app.dm.roles.models import DmUserRole, DmUserRoleLog
from app.services import AuditLogService

_AUDIENCE_GROUP_TYPE = "AUDIENCE"
_GRANT = "GRANT"
_REVOKE = "REVOKE"


class AssignService:
    """DM 角色 / 可見對象指派轉接層（§3）。"""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService()

    async def get_users_roles_audiences(self, db: AsyncSession, user_ids: list[str]) -> dict[str, AssignmentView]:
        """批次載入一頁使用者之 DM 角色 + 可見對象現況（避 N+1）；查無指派回空集合 View。"""
        result: dict[str, AssignmentView] = {
            uid: AssignmentView(frozenset(), frozenset(), None, None) for uid in user_ids
        }
        if not user_ids:
            return result

        roles: dict[str, set[str]] = {uid: set() for uid in user_ids}
        groups: dict[str, set[str]] = {uid: set() for uid in user_ids}
        last_by: dict[str, str | None] = {uid: None for uid in user_ids}
        last_at: dict[str, datetime | None] = {uid: None for uid in user_ids}

        role_rows = await db.execute(
            select(DmUserRole).where(DmUserRole.user_id.in_(user_ids), DmUserRole.deleted == 0)
        )
        for r in role_rows.scalars():
            roles[r.user_id].add(r.role_code)
            # 最後異動取 UPDATED_* or CREATED_*（新授予之列尚無 UPDATED_*）
            _track_last(last_by, last_at, r.user_id, r.updated_user or r.created_user, r.updated_date or r.created_date)

        tag_rows = await db.execute(select(DmUserTag).where(DmUserTag.user_id.in_(user_ids), DmUserTag.deleted == 0))
        for t in tag_rows.scalars():
            groups[t.user_id].add(str(t.tag_id))
            _track_last(last_by, last_at, t.user_id, t.updated_user or t.created_user, t.updated_date or t.created_date)

        for uid in user_ids:
            result[uid] = AssignmentView(
                roles=frozenset(roles[uid]),
                groups=frozenset(groups[uid]),
                last_modified_by=last_by[uid],
                last_modified_date=last_at[uid],
            )
        return result

    async def assign_roles_audiences(
        self, db: AsyncSession, *, user_id: str, roles: set[str], audiences: set[str], operator_id: str
    ) -> None:
        """設定使用者之 DM 角色與可見對象為目標集合（差異套用、即時生效）。

        Raises:
            AppError: operator 取消自己之管理者角色（403 DM_ROLE_001）、可見對象無效 / 未啟用（422 DM_ROLE_002）。
        """
        # 自我保護先於任何寫入：若 operator 對自己儲存之角色集不含 DM_ADMIN 即拒絕
        ensure_not_self_admin_removal(operator_id, user_id, roles)

        current = (await self.get_users_roles_audiences(db, [user_id]))[user_id]
        roles_add, roles_remove = roles - current.roles, current.roles - roles
        aud_add, aud_remove = audiences - current.groups, current.groups - audiences

        await self._validate_audiences_enabled(db, aud_add)

        for role in sorted(roles_remove):
            await self._set_role(db, user_id, role, active=False, operator_id=operator_id)
        for role in sorted(roles_add):
            await self._set_role(db, user_id, role, active=True, operator_id=operator_id)
        for tag_id in sorted(aud_remove):
            await self._set_audience(db, user_id, int(tag_id), active=False, operator_id=operator_id)
        for tag_id in sorted(aud_add):
            await self._set_audience(db, user_id, int(tag_id), active=True, operator_id=operator_id)

        await db.flush()
        await self._audit.log_action(
            db,
            module="DM",
            func_name="ROLES",
            action_type="ASSIGN",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=user_id,
            before_value={"roles": sorted(current.roles), "audiences": sorted(current.groups)},
            after_value={"roles": sorted(roles), "audiences": sorted(audiences)},
        )

    async def _set_role(self, db: AsyncSession, user_id: str, role: str, *, active: bool, operator_id: str) -> None:
        """授予 / 撤銷單一角色（軟刪除復用避開唯一約束）+ 寫 append-only log。"""
        row = await db.scalar(select(DmUserRole).where(DmUserRole.user_id == user_id, DmUserRole.role_code == role))
        now = utcnow()
        if active:
            if row is None:
                db.add(DmUserRole(user_id=user_id, role_code=role, created_user=operator_id, created_date=now))
            else:
                row.deleted = 0
                row.updated_user, row.updated_date = operator_id, now
        elif row is not None:
            row.deleted = 1
            row.updated_user, row.updated_date = operator_id, now
        db.add(
            DmUserRoleLog(
                target_user_id=user_id,
                role_code=role,
                action=_GRANT if active else _REVOKE,
                operator_user_id=operator_id,
                action_time=now,
                created_user=operator_id,
                created_date=now,
            )
        )

    async def _set_audience(
        self, db: AsyncSession, user_id: str, tag_id: int, *, active: bool, operator_id: str
    ) -> None:
        """授予 / 撤銷單一可見對象授權（軟刪除復用；最後異動記於 UPDATED_*）。"""
        row = await db.scalar(select(DmUserTag).where(DmUserTag.user_id == user_id, DmUserTag.tag_id == tag_id))
        now = utcnow()
        if active:
            if row is None:
                db.add(DmUserTag(user_id=user_id, tag_id=tag_id, created_user=operator_id, created_date=now))
            else:
                row.deleted = 0
                row.updated_user, row.updated_date = operator_id, now
        elif row is not None:
            row.deleted = 1
            row.updated_user, row.updated_date = operator_id, now

    async def _validate_audiences_enabled(self, db: AsyncSession, tag_ids: set[str]) -> None:
        """新增之可見對象 MUST 屬 AUDIENCE 組且啟用；否則 DM_ROLE_002。"""
        if not tag_ids:
            return
        ints = {int(t) for t in tag_ids}
        valid = await db.execute(
            select(DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(
                DmTag.tag_id.in_(ints),
                DmTag.is_enabled.is_(True),
                DmTagGroup.group_type == _AUDIENCE_GROUP_TYPE,
            )
        )
        valid_ids = set(valid.scalars())
        if ints - valid_ids:
            raise AppError(status_code=422, detail="指定之可見對象無效或未啟用", error_code="DM_ROLE_002")


def _track_last(
    last_by: dict[str, str | None], last_at: dict[str, datetime | None], uid: str, user: str | None, at: datetime | None
) -> None:
    """記錄某使用者最新一筆異動之 UPDATED_USER / UPDATED_DATE（供「最後異動」欄）。"""
    if at is not None and (last_at[uid] is None or at > last_at[uid]):
        last_at[uid] = at
        last_by[uid] = user
