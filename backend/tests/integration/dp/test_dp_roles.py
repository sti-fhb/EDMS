"""US7 權限管理（dp-roles）轉接層整合測試（真 DM provider end-to-end）。

驗證：可管理模組（DM real / ET fail-closed）、模組過濾越權 403、指派委派 DM provider 寫模組表 + 稽核、
自我保護映射 DP_ROLE_002、群組選項、列現況；另一條 HTTP 驗 router 認證接線。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.module_roles import module_role_gate
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.bootstrap import register_dm_module
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR
from app.dm.roles.models import DmUserRole
from app.dp.audit.models import DpAuditLog
from app.dp.roles.service import RolesService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = RolesService()


@pytest.fixture
def dm_registered():
    """註冊真 DM provider + DM is_module_admin / has_any_role（查 DM_USER_ROLE）；teardown 清除避免污染。"""
    register_dm_module()
    yield
    module_assign_registry.unregister("DM")
    module_admin_gate.unregister("DM")
    module_role_gate.unregister("DM")


async def _grant_dm(db, user_id: str, role: str) -> None:
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user=user_id, created_date=utcnow()))
    await db.flush()


async def _seed_user(db, user_id: str, *, status: str = "ACTIVE", locked_until=None) -> None:
    """建 DP_USER；`status` / `locked_until` 供 #250 停用 / 鎖定情境使用（預設為正常帳號）。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@example.com",
            pwd_hash="x",
            user_name=f"用戶{user_id}",
            status=status,
            locked_until=locked_until,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _audience_tag_id(db) -> int:
    return await db.scalar(
        select(DmTag.tag_id)
        .join(DmTagGroup)
        .where(DmTagGroup.group_type == "AUDIENCE", DmTag.is_enabled.is_(True))
        .limit(1)
    )


async def test_manageable_modules_dm_admin_only(db, dm_registered):
    """DM 管理者 → 可管理模組含 DM；ET 未註冊 → 不出現。"""
    await _grant_dm(db, "op_admin", DM_ADMIN)
    assert await _svc.manageable_modules(db, "op_admin") == ["DM"]


async def test_manageable_modules_non_admin_empty(db, dm_registered):
    """非 DM 管理者（僅編輯者）→ 無可管理模組。"""
    await _grant_dm(db, "op_ed", DM_EDITOR)
    assert await _svc.manageable_modules(db, "op_ed") == []


async def test_require_manageable_enforces(db, dm_registered):
    """非 DM 管理者操作 DM → 403 DP_ROLE_001；未註冊模組 → 404 DP_ROLE_003。

    未註冊模組原以 "ET" 為例，**2026-08-20（#185）ET Foundation 落地後改用 "XX"**：
    `main.py` 已於 module-level 呼叫 `register_et_module()`，任何 import main 之測試
    （如 `client` fixture）都會使 ET 成為已註冊模組，該前提不再成立。改用一個
    **永不會被註冊**的模組碼，才是對「未註冊 → 404」這條規則的穩定驗證。
    """
    with pytest.raises(AppError) as e1:
        await _svc.group_options(db, module="DM", user_id="nobody")
    assert e1.value.status_code == 403 and e1.value.error_code == "DP_ROLE_001"
    await _grant_dm(db, "adm", DM_ADMIN)
    with pytest.raises(AppError) as e2:
        await _svc.list_assignments(
            db, module="XX", keyword=None, page=1, limit=20, operator=OperatorInfo(user_id="adm")
        )
    assert e2.value.status_code == 404 and e2.value.error_code == "DP_ROLE_003"  # XX 永不註冊 provider


async def test_assign_delegates_to_dm_provider_and_audits(db, dm_registered):
    """DM 管理者指派 → 委派 DM provider 寫 DM_USER_ROLE / DM_USER_TAG + 模組側稽核。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    tag_id = await _audience_tag_id(db)
    op = OperatorInfo(user_id="adm")
    await _svc.assign(db, module="DM", user_id="tgt", roles=[DM_EDITOR], groups=[str(tag_id)], operator=op)
    roles = {
        r
        for r in (
            await db.execute(select(DmUserRole.role_code).where(DmUserRole.user_id == "tgt", DmUserRole.deleted == 0))
        ).scalars()
    }
    assert roles == {DM_EDITOR}
    audit = await db.scalar(
        select(func.count()).select_from(DpAuditLog).where(DpAuditLog.module == "DM", DpAuditLog.target_id == "tgt")
    )
    assert audit >= 1


async def test_self_protection_mapped_to_dp_role_002(db, dm_registered):
    """operator 取消自己之 DM_ADMIN → 模組 raise → DP 映射 DP_ROLE_002（403）。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    with pytest.raises(AppError) as e:
        await _svc.assign(
            db, module="DM", user_id="adm", roles=[DM_EDITOR], groups=[], operator=OperatorInfo(user_id="adm")
        )
    assert e.value.status_code == 403 and e.value.error_code == "DP_ROLE_002"


async def test_group_options_returns_audiences(db, dm_registered):
    """DM group-options 回啟用中 AUDIENCE 標籤。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    opts = await _svc.group_options(db, module="DM", user_id="adm")
    assert len(opts) >= 1 and all(o.code and o.name for o in opts)


async def test_list_assignments_merges_current(db, dm_registered):
    """列使用者 + 現況：已指派者顯示其 DM 角色。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    await _seed_user(db, "u_tgt")
    await _svc.assign(
        db, module="DM", user_id="u_tgt", roles=[DM_EDITOR], groups=[], operator=OperatorInfo(user_id="adm")
    )
    result = await _svc.list_assignments(
        db, module="DM", keyword="u_tgt", page=1, limit=20, operator=OperatorInfo(user_id="adm")
    )
    row = next((i for i in result["data"] if i.user_id == "u_tgt"), None)
    assert row is not None and DM_EDITOR in row.roles


async def test_list_assignments_resolves_modifier_name(db, dm_registered):
    """最後異動者 USER_ID 解析為顯示名（姓名，無則 email）——畫面顯示人名而非原始 ID。"""
    await _seed_user(db, "op_adm")  # 操作者須為 DP_USER 才解析得到姓名
    await _grant_dm(db, "op_adm", DM_ADMIN)
    await _seed_user(db, "u_mod")
    op = OperatorInfo(user_id="op_adm")
    await _svc.assign(db, module="DM", user_id="u_mod", roles=[DM_EDITOR], groups=[], operator=op)
    result = await _svc.list_assignments(db, module="DM", keyword="u_mod", page=1, limit=20, operator=op)
    row = next((i for i in result["data"] if i.user_id == "u_mod"), None)
    assert row is not None
    assert row.last_modified_by == "op_adm"  # 原始 USER_ID 仍保留
    assert row.last_modified_by_name == "用戶op_adm"  # 解析姓名（_seed_user 設 user_name=用戶{id}）


async def test_list_assignments_exposes_account_status(db, dm_registered):
    """列表帶出帳號狀態（#250 AC1/AC2 資料基礎）：畫面據此灰化停用 / 鎖定列。

    `locked_until` 原樣輸出、不由後端算「是否鎖定中」——與 dp-users 列表同慣例
    （`UserResponse` docstring：已鎖定由前端以 `locked_until > now` 衍生，避免序列化取系統時間）。
    """
    await _grant_dm(db, "adm", DM_ADMIN)
    await _seed_user(db, "u_ok")
    await _seed_user(db, "u_off", status="DISABLED")
    lock_until = utcnow() + timedelta(hours=1)
    await _seed_user(db, "u_lock", locked_until=lock_until)

    result = await _svc.list_assignments(
        db, module="DM", keyword=None, page=1, limit=100, operator=OperatorInfo(user_id="adm")
    )
    by_id = {i.user_id: i for i in result["data"]}
    assert by_id["u_ok"].status == "ACTIVE" and by_id["u_ok"].locked_until is None
    assert by_id["u_off"].status == "DISABLED"
    assert by_id["u_lock"].status == "ACTIVE" and by_id["u_lock"].locked_until is not None


async def test_assign_rejects_disabled_account(db, dm_registered):
    """對已停用帳號指派角色 → 403 DP_ROLE_004（#250 AC3，擋前端繞過）。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    await _seed_user(db, "u_off", status="DISABLED")
    with pytest.raises(AppError) as e:
        await _svc.assign(
            db, module="DM", user_id="u_off", roles=[DM_EDITOR], groups=[], operator=OperatorInfo(user_id="adm")
        )
    assert e.value.status_code == 403 and e.value.error_code == "DP_ROLE_004"


async def test_assign_rejects_locked_account(db, dm_registered):
    """對鎖定中帳號指派角色 → 403 DP_ROLE_004（#250 AC3）。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    await _seed_user(db, "u_lock", locked_until=utcnow() + timedelta(hours=1))
    with pytest.raises(AppError) as e:
        await _svc.assign(
            db, module="DM", user_id="u_lock", roles=[DM_EDITOR], groups=[], operator=OperatorInfo(user_id="adm")
        )
    assert e.value.status_code == 403 and e.value.error_code == "DP_ROLE_004"


async def test_assign_allows_account_with_expired_lock(db, dm_registered):
    """鎖定已逾時（自動解鎖）之帳號可正常指派——不可誤以 `LOCKED_UNTIL IS NOT NULL` 判定。"""
    await _grant_dm(db, "adm", DM_ADMIN)
    await _seed_user(db, "u_exp", locked_until=utcnow() - timedelta(minutes=1))
    await _svc.assign(
        db, module="DM", user_id="u_exp", roles=[DM_EDITOR], groups=[], operator=OperatorInfo(user_id="adm")
    )
    roles = {
        r
        for r in (
            await db.execute(
                select(DmUserRole.role_code).where(DmUserRole.user_id == "u_exp", DmUserRole.deleted == 0)
            )
        ).scalars()
    }
    assert roles == {DM_EDITOR}


async def test_http_requires_auth(db, dm_registered, client):
    """router 掛認證：未帶 token → 401。"""
    resp = await client.get("/api/dp/roles/modules")
    assert resp.status_code == 401


async def test_http_modules_authed(db, dm_registered, client):
    """認證後 GET /modules 回可管理模組（DM）。"""
    await _seed_user(db, "httpadm")  # get_jwt_payload 每請求查 DP_USER，需存在且 ACTIVE
    await _grant_dm(db, "httpadm", DM_ADMIN)
    token = create_access_token(sub="httpadm", ttl_minutes=15)
    resp = await client.get("/api/dp/roles/modules", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and "DM" in resp.json()


async def test_http_put_non_admin_forbidden(db, dm_registered, client):
    """越權：非 DM 管理者 HTTP PUT 指派 DM 角色 → 403（router→service 串接 enforce）。"""
    await _seed_user(db, "httpnon")
    token = create_access_token(sub="httpnon", ttl_minutes=15)
    resp = await client.put(
        "/api/dp/roles/DM/assignments/victim",
        json={"roles": ["DM_ADMIN"], "groups": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
