"""廠商維運帳號（`edmsops`，#927）整合測試。

帳號由 migration `36af0d3943bf` 無條件種入（測試 DB 同樣以 `alembic upgrade head` 建置，故本檔
直接使用它，不另建）。驗的是**行為**：具全部功能權限、不被閒置停用、停用 / 拿掉預設角色被擋、
解鎖 / 加角色 / 改群組 / 本人改姓名照常。

每條「擋」都配一條同一路徑對一般帳號或非保護欄位放行的對照，確認擋下的理由是保護規則。
⚠️ 依 integration-test-rollback 慣例，一條測試只放一次預期失敗的呼叫。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.ops_account import OPS_USER_ID
from app.core.utils import utcnow
from app.dm.bootstrap import register_dm_module
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.kpi.service import KpiService
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER, OPS_DM_ROLES
from app.dm.roles.models import DmUserRole
from app.dm.roles.reviewer_query import assignable_reviewers_stmt
from app.dp.roles.service import RolesService
from app.dp.users.models import DpUser
from app.dp.users.service import UsersService
from app.et.bootstrap import register_et_module
from app.et.constants import ROLE_ADMIN, ROLE_TEACHER
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_roles = RolesService()
_users = UsersService()
_OPS_EMAIL = "tbsfnoreply@gmail.com"


@pytest.fixture(autouse=True)
def modules_registered():
    """確保 DM / ET 之真實閘與 provider 已註冊。

    其他測試檔的 teardown 可能 unregister 掉 main.py 註冊的真實 checker（同 worker 先跑時
    會留下空的聚合閘），故這裡重新註冊；註冊的就是正式環境的狀態，不需 teardown。
    """
    register_dm_module()
    register_et_module()


async def _seed_user(db, user_id: str, *, created=None, last_login=None) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@example.com",
            pwd_hash="x",
            user_name=f"用戶{user_id}",
            status="ACTIVE",
            pwd_changed_date=now,
            last_login_date=last_login,
            created_user="seed",
            created_date=created or now,
        )
    )
    await db.flush()


async def _dm_admin_operator(db) -> OperatorInfo:
    await _seed_user(db, "op_dm")
    db.add(DmUserRole(user_id="op_dm", role_code=DM_ADMIN, created_user="seed", created_date=utcnow()))
    await db.flush()
    return OperatorInfo(user_id="op_dm")


async def _dm_audience_group(db) -> str:
    """DM 之群組值＝(單位, 職位) 配對編碼（同 test_dp_roles.py）。"""
    unit_id = await db.scalar(
        select(DmTag.tag_id)
        .join(DmTagGroup)
        .where(DmTagGroup.group_type == "UNIT", DmTag.tag_name != "全單位", DmTag.is_enabled.is_(True))
        .limit(1)
    )
    audience_id = await db.scalar(
        select(DmTag.tag_id)
        .join(DmTagGroup)
        .where(DmTagGroup.group_type == "AUDIENCE", DmTag.is_enabled.is_(True))
        .limit(1)
    )
    return f"{unit_id}:{audience_id}"


async def _ops_status(db) -> str:
    return await db.scalar(select(DpUser.status).where(DpUser.user_id == OPS_USER_ID))


# ── 全部功能權限 ─────────────────────────────────────────────────────


async def test_ops_account_has_all_module_permissions(db):
    """維運帳號為 DM、ET 管理者，且可被指定為 DM 審核者（簽核中心需 DM_REVIEWER）。"""
    assert await module_admin_gate.is_module_admin("DM", OPS_USER_ID, db) is True
    assert await module_admin_gate.is_module_admin("ET", OPS_USER_ID, db) is True
    reviewers = {row.user_id for row in await db.execute(assignable_reviewers_stmt(utcnow()))}
    assert OPS_USER_ID in reviewers


async def test_ops_account_receives_dm_weekly_report(db):
    """維運帳號為 DM 管理者，會收到 DM KPI 週報（issue 注意事項所列的預期收信）。

    其他以「全部管理者」為母體的測試以 `ops_account_without_roles` 撤下本帳號角色，
    本條是那一面的正向錨點：日後若有人誤把維運帳號排出管理者母體，這裡會紅。
    """
    await KpiService().run_weekly(db)

    recipients = set(
        await db.scalars(
            text('SELECT "RECIPIENT" FROM "DP_EMAIL_LOG" WHERE "MODULE" = \'DM\' AND "TEMPLATE_CODE" = \'KPI_WEEKLY\'')
        )
    )
    assert _OPS_EMAIL in recipients


# ── 閒置停用排程 ─────────────────────────────────────────────────────


async def test_idle_disable_skips_ops_account(db):
    """從未登入且建立逾閒置天數的維運帳號不被停用；同條件的一般帳號照常停用（對照）。"""
    long_ago = utcnow() - timedelta(days=400)
    await db.execute(update(DpUser).where(DpUser.user_id == OPS_USER_ID).values(created_date=long_ago))
    await _seed_user(db, "idle_peer", created=long_ago)

    disabled = await _users.disable_idle_accounts(db)

    assert disabled == 1
    assert await _ops_status(db) == "ACTIVE"
    assert await db.scalar(select(DpUser.status).where(DpUser.user_id == "idle_peer")) == "DISABLED"


# ── 使用者管理 ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("backoffice_admin")
async def test_disable_ops_account_via_api_blocked(db, client):
    """經 API 停用維運帳號 → 403 DP_USER_012，帳號仍為 ACTIVE。"""
    token = create_access_token(sub="admin01", ttl_minutes=15)
    await _seed_user(db, "admin01")

    resp = await client.patch(
        f"/api/dp/users/{OPS_USER_ID}/status",
        json={"action": "disable"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "DP_USER_012"
    assert await _ops_status(db) == "ACTIVE"


async def test_unlock_ops_account_allowed(db):
    """被連打錯密碼鎖住的維運帳號，管理者可解鎖。"""
    await db.execute(
        update(DpUser)
        .where(DpUser.user_id == OPS_USER_ID)
        .values(login_fail_count=5, locked_until=utcnow() + timedelta(minutes=30))
    )

    await _users.unlock(db, user_id=OPS_USER_ID, operator=OperatorInfo(user_id="admin01"))

    user = await db.scalar(select(DpUser).where(DpUser.user_id == OPS_USER_ID))
    assert (user.login_fail_count, user.locked_until) == (0, None)


async def test_ops_account_can_rename_self_via_profile(db, client):
    """本人經個人資料維護（US8）改自己的姓名照常——保護只針對管理者路徑。"""
    token = create_access_token(sub=OPS_USER_ID, ttl_minutes=15)

    resp = await client.put(
        "/api/dp/user/me", json={"user_name": "廠商維運"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 204
    assert await db.scalar(select(DpUser.user_name).where(DpUser.user_id == OPS_USER_ID)) == "廠商維運"


# ── 權限管理：DM ─────────────────────────────────────────────────────


async def test_dm_remove_default_role_blocked(db):
    """拿掉維運帳號任一 DM 預設角色 → 403 DM_ROLE_004，角色不變。"""
    operator = await _dm_admin_operator(db)

    with pytest.raises(AppError) as e:
        await _roles.assign(
            db,
            module="DM",
            user_id=OPS_USER_ID,
            roles=sorted(OPS_DM_ROLES - {"DM_REVIEWER"}),
            groups=[],
            operator=operator,
        )

    assert (e.value.status_code, e.value.error_code) == (403, "DM_ROLE_004")
    active = set(
        await db.scalars(select(DmUserRole.role_code).where(DmUserRole.user_id == OPS_USER_ID, DmUserRole.deleted == 0))
    )
    assert active == OPS_DM_ROLES


async def test_dm_change_groups_keeping_roles_allowed(db):
    """保留預設角色、另加 DM_VIEWER 並異動可見對象 → 照常寫入。"""
    operator = await _dm_admin_operator(db)
    group = await _dm_audience_group(db)
    roles = sorted(OPS_DM_ROLES | {DM_VIEWER})

    await _roles.assign(db, module="DM", user_id=OPS_USER_ID, roles=roles, groups=[group], operator=operator)

    view = await _roles.list_assignments(db, module="DM", keyword=OPS_USER_ID, page=1, limit=10, operator=operator)
    item = next(i for i in view["data"] if i.user_id == OPS_USER_ID)
    assert (item.roles, item.groups) == (roles, [group])


# ── 權限管理：ET ─────────────────────────────────────────────────────


async def _et_active_roles(db) -> set[str]:
    return set(
        await db.scalars(
            select(EtUserRole.role).where(
                EtUserRole.user_id == OPS_USER_ID, EtUserRole.is_active.is_(True), EtUserRole.deleted == 0
            )
        )
    )


async def test_et_other_admin_removing_ops_admin_blocked(db):
    """其他 ET 管理者拿掉維運帳號的 ADMIN → 403 ET_ROLE_005，角色不變。"""
    await _seed_user(db, "op_et")
    db.add(EtUserRole(user_id="op_et", role=ROLE_ADMIN, is_active=True, created_user="seed", created_date=utcnow()))
    await db.flush()

    with pytest.raises(AppError) as e:
        await _roles.assign(
            db,
            module="ET",
            user_id=OPS_USER_ID,
            roles=[ROLE_TEACHER],
            groups=[],
            operator=OperatorInfo(user_id="op_et"),
        )

    assert (e.value.status_code, e.value.error_code) == (403, "ET_ROLE_005")
    assert await _et_active_roles(db) == {ROLE_ADMIN}


async def test_et_ops_removing_own_admin_blocked(db):
    """維運帳號自己拿掉自己的 ET ADMIN → 403 ET_ROLE_005（先於「不可取消自己的管理者」判斷）。

    ⚠️ 自我保護（ET_ROLE_001）同樣會擋這個請求；本條斷言錯誤碼為 ET_ROLE_005，確認是維運帳號規則擋下。
    """
    with pytest.raises(AppError) as e:
        await _roles.assign(
            db,
            module="ET",
            user_id=OPS_USER_ID,
            roles=[ROLE_TEACHER],
            groups=[],
            operator=OperatorInfo(user_id=OPS_USER_ID),
        )

    assert e.value.error_code == "ET_ROLE_005"
    assert await _et_active_roles(db) == {ROLE_ADMIN}


async def test_et_add_extra_role_allowed(db):
    """保留 ADMIN、另加 TEACHER → 照常寫入。"""
    await _roles.assign(
        db,
        module="ET",
        user_id=OPS_USER_ID,
        roles=[ROLE_ADMIN, ROLE_TEACHER],
        groups=[],
        operator=OperatorInfo(user_id=OPS_USER_ID),
    )

    assert await _et_active_roles(db) == {ROLE_ADMIN, ROLE_TEACHER}
