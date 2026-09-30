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
from app.dm.roles.authz import DM_ROLES, ensure_not_self_admin_removal
from app.dm.roles.models import DmUserRole, DmUserRoleLog
from app.services import AuditLogService

_AUDIENCE_GROUP_TYPE = "AUDIENCE"
_UNIT_GROUP_TYPE = "UNIT"  # 單位標籤組（#437）
_MAX_BIGINT = 2**63 - 1
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
            groups[t.user_id].add(encode_pair(t.unit_tag_id, t.tag_id))
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
        # 輸入防呆（本轉接層為 DM_USER_ROLE / DM_USER_TAG 之權威寫入口，不信任呼叫端）
        _ensure_valid_roles(roles)
        _ensure_valid_pairs(audiences)
        # 自我保護先於任何寫入：若 operator 對自己儲存之角色集不含 DM_ADMIN 即拒絕
        ensure_not_self_admin_removal(operator_id, user_id, roles)

        current = (await self.get_users_roles_audiences(db, [user_id]))[user_id]
        roles_add, roles_remove = roles - current.roles, current.roles - roles
        aud_add, aud_remove = audiences - current.groups, current.groups - audiences
        if not (roles_add or roles_remove or aud_add or aud_remove):
            return  # 無實際異動：不寫入、不記稽核（僅記真正的指派異動）

        await self._validate_audiences_enabled(db, aud_add)

        for role in sorted(roles_remove):
            await self._set_role(db, user_id, role, active=False, operator_id=operator_id)
        for role in sorted(roles_add):
            await self._set_role(db, user_id, role, active=True, operator_id=operator_id)
        for pair in sorted(aud_remove):
            unit_id, role_id = decode_pair(pair)
            await self._set_audience(db, user_id, role_id, unit_id, active=False, operator_id=operator_id)
        for pair in sorted(aud_add):
            unit_id, role_id = decode_pair(pair)
            await self._set_audience(db, user_id, role_id, unit_id, active=True, operator_id=operator_id)

        await db.flush()
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-ROLES",
            action_type="UPDATE",
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
        self, db: AsyncSession, user_id: str, tag_id: int, unit_tag_id: int | None, *, active: bool, operator_id: str
    ) -> None:
        """授予 / 撤銷單一 (單位, 職位) 配對授權（軟刪除復用；最後異動記於 UPDATED_*）。

        查詢鍵為 `(USER_ID, TAG_ID, UNIT_TAG_ID)` 整組（#437）——同一職位可對應多個單位，
        僅以 `TAG_ID` 定位會撈到另一個單位的配對並就地改掉。

        `unit_tag_id` 為 None 代表單位未指定（導入配對前之既有授權），以 `IS NULL` 比對。
        """
        unit_match = DmUserTag.unit_tag_id.is_(None) if unit_tag_id is None else DmUserTag.unit_tag_id == unit_tag_id
        row = await db.scalar(
            select(DmUserTag).where(DmUserTag.user_id == user_id, DmUserTag.tag_id == tag_id, unit_match)
        )
        now = utcnow()
        if active:
            if row is None:
                db.add(
                    DmUserTag(
                        user_id=user_id,
                        tag_id=tag_id,
                        unit_tag_id=unit_tag_id,
                        created_user=operator_id,
                        created_date=now,
                    )
                )
            else:
                row.deleted = 0
                row.updated_user, row.updated_date = operator_id, now
        elif row is not None:
            row.deleted = 1
            row.updated_user, row.updated_date = operator_id, now

    async def _validate_audiences_enabled(self, db: AsyncSession, pairs: set[str]) -> None:
        """新增之配對兩端 MUST 各屬 AUDIENCE / UNIT 組且啟用；否則 DM_ROLE_002。

        兩端分別驗組別（#437）：職位放到單位欄（或反之）於 DB 層無從攔截——`UNIT_TAG_ID` 之 FK
        只能保證指向 `DM_TAG`。人側之單位允許未指定（None），該情形不需驗。
        """
        if not pairs:
            return
        decoded = [decode_pair(p) for p in pairs]
        role_ids = {role_id for _, role_id in decoded}
        unit_ids = {unit_id for unit_id, _ in decoded if unit_id is not None}
        await self._ensure_tags_in_group(db, role_ids, _AUDIENCE_GROUP_TYPE)
        await self._ensure_tags_in_group(db, unit_ids, _UNIT_GROUP_TYPE)

    async def _ensure_tags_in_group(self, db: AsyncSession, tag_ids: set[int], group_type: str) -> None:
        """指定標籤全數存在、啟用中且屬該組型；否則 DM_ROLE_002。"""
        if not tag_ids:
            return
        valid = await db.execute(
            select(DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(
                DmTag.tag_id.in_(tag_ids),
                DmTag.is_enabled.is_(True),
                DmTagGroup.group_type == group_type,
            )
        )
        if tag_ids - set(valid.scalars()):
            raise AppError(status_code=422, detail="指定之可見對象無效或未啟用", error_code="DM_ROLE_002")


def encode_pair(unit_tag_id: int | None, tag_id: int) -> str:
    """把 (單位, 職位) 配對編為 `"{unit}:{role}"`（#437）。

    `AssignmentView.groups` 之元素型別為 `str`（跨模組共用契約，各模組自定語意），故 DM 以此
    字串攜帶配對。單位未指定者編為 `":{role}"`——空字串與任何 TAG_ID 皆不相等，集合差異運算
    因此能正確區分「未指定單位」與「某個具體單位」兩種授權。
    """
    return f"{'' if unit_tag_id is None else unit_tag_id}:{tag_id}"


def decode_pair(pair: str) -> tuple[int | None, int]:
    """把 `encode_pair` 之字串解回 `(單位 TAG_ID | None, 職位 TAG_ID)`。"""
    unit_str, _, role_str = pair.partition(":")
    return (int(unit_str) if unit_str else None), int(role_str)


def _ensure_valid_roles(roles: set[str]) -> None:
    """角色 MUST 屬固定 enum DM_ROLES；否則 DM_ROLE_003。"""
    if roles - DM_ROLES:
        raise AppError(status_code=422, detail="指定之角色代碼無效", error_code="DM_ROLE_003")


def _is_valid_tag_id(value: str) -> bool:
    """字串可安全轉為 BIGINT 範圍內之正整數 TAG_ID。

    用 `isdecimal()` 而非 `isdigit()`——後者對 Unicode 數字字元（`²` / `①`）回 True 但 `int()`
    會拋 ValueError；另加 BIGINT 界限，否則超長數字會在 asyncpg 綁參數時拋 DataError。兩者皆為
    未攔截的 500。比照 `app/dm/catalog/adapter.py` 之 `_tag_id`。
    """
    return value.isdecimal() and len(value) <= 19 and 0 < int(value) <= _MAX_BIGINT


def _ensure_valid_pairs(pairs: set[str]) -> None:
    """可見對象值 MUST 為 `"{unit}:{role}"` 格式（單位可空）；否則 DM_ROLE_002。

    防呆先於任何 `int()` 轉型——格式錯誤若流到 `decode_pair` 會丟 ValueError 而非 422。
    """
    for p in pairs:
        unit_str, sep, role_str = p.partition(":")
        if not sep or not _is_valid_tag_id(role_str) or (unit_str and not _is_valid_tag_id(unit_str)):
            raise AppError(status_code=422, detail="指定之可見對象無效或未啟用", error_code="DM_ROLE_002")


def _track_last(
    last_by: dict[str, str | None], last_at: dict[str, datetime | None], uid: str, user: str | None, at: datetime | None
) -> None:
    """記錄某使用者最新一筆異動之 UPDATED_USER / UPDATED_DATE（供「最後異動」欄）。"""
    if at is not None and (last_at[uid] is None or at > last_at[uid]):
        last_at[uid] = at
        last_by[uid] = user
