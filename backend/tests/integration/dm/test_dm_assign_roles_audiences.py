"""DM 角色 / 可見對象指派服務整合測試（§3，真實 DB）。

驗證：批次現況載入、角色 GRANT/REVOKE 寫 DM_USER_ROLE(_LOG)、可見對象授權、
自我保護 DM_ROLE_001、可見對象非啟用拒絕 DM_ROLE_002、同交易 SRVDP003 稽核。
"""

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AppError
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.roles.assign_service import AssignService
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole, DmUserRoleLog

pytestmark = pytest.mark.integration

_svc = AssignService()


async def _audience_tag_id(db) -> int:
    """取一個已種之啟用 AUDIENCE 標籤 TAG_ID（#127 種了全體 / 護理師…）。"""
    return await db.scalar(
        select(DmTag.tag_id)
        .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
        .where(DmTagGroup.group_type == "AUDIENCE", DmTag.is_enabled.is_(True))
        .limit(1)
    )


async def test_get_returns_empty_view_for_unknown(db):
    """查無指派之使用者回空集合 View（非缺 key）。"""
    views = await _svc.get_users_roles_audiences(db, ["AS_NONE", "AS_X"])
    assert set(views) == {"AS_NONE", "AS_X"}
    assert views["AS_NONE"].roles == frozenset() and views["AS_NONE"].groups == frozenset()


async def test_assign_grants_roles_and_writes_log(db):
    """指派角色 → DM_USER_ROLE 有列 + DM_USER_ROLE_LOG 記 GRANT。"""
    await _svc.assign_roles_audiences(
        db, user_id="AS_U1", roles={DM_EDITOR, DM_REVIEWER}, audiences=set(), operator_id="ADMIN"
    )
    view = (await _svc.get_users_roles_audiences(db, ["AS_U1"]))["AS_U1"]
    assert view.roles == frozenset({DM_EDITOR, DM_REVIEWER})
    assert view.last_modified_by == "ADMIN"
    grants = await db.scalar(
        select(func.count())
        .select_from(DmUserRoleLog)
        .where(DmUserRoleLog.target_user_id == "AS_U1", DmUserRoleLog.action == "GRANT")
    )
    assert grants == 2


async def test_revoke_soft_deletes_and_regrant_reuses_row(db):
    """撤銷角色 → 軟刪除 + LOG REVOKE；再授予復用同列（不違反唯一約束）。"""
    await _svc.assign_roles_audiences(db, user_id="AS_U2", roles={DM_EDITOR}, audiences=set(), operator_id="ADMIN")
    await _svc.assign_roles_audiences(db, user_id="AS_U2", roles=set(), audiences=set(), operator_id="ADMIN")  # 撤銷
    view = (await _svc.get_users_roles_audiences(db, ["AS_U2"]))["AS_U2"]
    assert view.roles == frozenset()
    await _svc.assign_roles_audiences(
        db, user_id="AS_U2", roles={DM_EDITOR}, audiences=set(), operator_id="ADMIN"
    )  # 再授予
    view = (await _svc.get_users_roles_audiences(db, ["AS_U2"]))["AS_U2"]
    assert view.roles == frozenset({DM_EDITOR})
    rows = await db.scalar(
        select(func.count())
        .select_from(DmUserRole)
        .where(DmUserRole.user_id == "AS_U2", DmUserRole.role_code == DM_EDITOR)
    )
    assert rows == 1  # 復用同列、未新增第二列


async def test_self_admin_removal_blocked(db):
    """operator 對自己儲存不含 DM_ADMIN 之角色集 → DM_ROLE_001。"""
    with pytest.raises(AppError) as e:
        await _svc.assign_roles_audiences(db, user_id="AS_OP", roles={DM_EDITOR}, audiences=set(), operator_id="AS_OP")
    assert e.value.error_code == "DM_ROLE_001"


async def test_admin_can_remove_other_admin(db):
    """管理者間可互相停用（不檢核至少 1 名管理者）。"""
    await _svc.assign_roles_audiences(db, user_id="AS_B", roles={DM_ADMIN}, audiences=set(), operator_id="AS_A")
    await _svc.assign_roles_audiences(db, user_id="AS_B", roles=set(), audiences=set(), operator_id="AS_A")
    view = (await _svc.get_users_roles_audiences(db, ["AS_B"]))["AS_B"]
    assert view.roles == frozenset()


async def test_assign_audience_and_disabled_rejected(db):
    """有效 AUDIENCE 授權寫入；非 AUDIENCE / 未啟用之 tag_id → DM_ROLE_002。"""
    tag_id = await _audience_tag_id(db)
    await _svc.assign_roles_audiences(
        db, user_id="AS_V", roles={DM_EDITOR}, audiences={str(tag_id)}, operator_id="ADMIN"
    )
    view = (await _svc.get_users_roles_audiences(db, ["AS_V"]))["AS_V"]
    assert str(tag_id) in view.groups
    granted = await db.scalar(
        select(func.count()).select_from(DmUserTag).where(DmUserTag.user_id == "AS_V", DmUserTag.deleted == 0)
    )
    assert granted == 1
    with pytest.raises(AppError) as e:
        await _svc.assign_roles_audiences(
            db, user_id="AS_V", roles={DM_EDITOR}, audiences={"999999"}, operator_id="ADMIN"
        )
    assert e.value.error_code == "DM_ROLE_002"


async def test_assign_writes_audit(db):
    """指派於同交易寫 SRVDP003 稽核（MODULE=DM）。"""
    from sqlalchemy import text

    await _svc.assign_roles_audiences(db, user_id="AS_AUD", roles={DM_EDITOR}, audiences=set(), operator_id="ADMIN")
    cnt = await db.scalar(
        text('SELECT count(*) FROM "DP_AUDIT_LOG" WHERE "MODULE"=\'DM\' AND "TARGET_ID"=:t'),
        {"t": "AS_AUD"},
    )
    assert cnt >= 1
