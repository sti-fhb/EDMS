"""ET 存取閘與四閘註冊整合測試（AC 5 / AC 6；#185）。

存取閘重用平台 DP 認證，以 `ET_USER_ROLE` 判准入——需真 DB 故為 integration。
"""

import pytest

from app.core.auth import JwtPayload
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.module_provisioning import module_provisioning_gate
from app.core.module_roles import module_role_gate
from app.core.utils import utcnow
from app.et.bootstrap import register_et_module
from app.et.constants import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER
from app.et.deps import EtContext, get_et_context, load_et_roles
from app.et.roles.models import EtUserRole
from app.et.roles.provisioning import grant_default_student_role

pytestmark = pytest.mark.integration


@pytest.fixture
def et_registered():
    """註冊 ET 四閘 checker / provider；**teardown 清除避免污染其他模組測試**。

    比照 `tests/integration/dp/test_dp_roles.py` 之 `dm_registered`。聚合閘為 module-level
    單例，若不清除會讓「未註冊模組 → fail-closed」類測試在同一 worker 內失準。
    """
    register_et_module()
    yield
    module_assign_registry.unregister("ET")
    module_admin_gate.unregister("ET")
    module_role_gate.unregister("ET")
    module_provisioning_gate.unregister("ET")


def _payload(user_id: str) -> JwtPayload:
    now = utcnow()
    return JwtPayload(sub=user_id, auth_time=now, iat=now, exp=now)


async def _grant(db, user_id: str, role: str, *, active: bool = True) -> None:
    db.add(
        EtUserRole(
            user_id=user_id,
            role=role,
            is_active=active,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


class TestAccessGate:
    async def test_load_roles_回傳已指派角色(self, db, et_registered) -> None:
        await _grant(db, "ET_GATE_U1", ROLE_TEACHER)
        assert await load_et_roles(db, "ET_GATE_U1") == frozenset({ROLE_TEACHER})

    async def test_無任何_et_角色者被擋(self, db, et_registered) -> None:
        """已通過平台認證但無 ET 角色 → 403 ET_AUTH_001。"""
        with pytest.raises(AppError) as e:
            await get_et_context(payload=_payload("ET_GATE_NONE"), db=db)
        assert e.value.status_code == 403
        assert e.value.error_code == "ET_AUTH_001"

    async def test_具_et_角色者放行並帶出角色集(self, db, et_registered) -> None:
        await _grant(db, "ET_GATE_U2", ROLE_STUDENT)
        ctx = await get_et_context(payload=_payload("ET_GATE_U2"), db=db)
        assert isinstance(ctx, EtContext)
        assert ctx.user_id == "ET_GATE_U2"
        assert ctx.roles == frozenset({ROLE_STUDENT})

    async def test_停用之角色不計入(self, db, et_registered) -> None:
        """IS_ACTIVE=false 之指派不得使該使用者通過存取閘。"""
        await _grant(db, "ET_GATE_U3", ROLE_TEACHER, active=False)
        assert await load_et_roles(db, "ET_GATE_U3") == frozenset()
        with pytest.raises(AppError) as e:
            await get_et_context(payload=_payload("ET_GATE_U3"), db=db)
        assert e.value.error_code == "ET_AUTH_001"

    async def test_多重角色取聯集(self, db, et_registered) -> None:
        await _grant(db, "ET_GATE_U4", ROLE_TEACHER)
        await _grant(db, "ET_GATE_U4", ROLE_STUDENT)
        assert await load_et_roles(db, "ET_GATE_U4") == frozenset({ROLE_TEACHER, ROLE_STUDENT})


class TestModuleGateRegistration:
    """AC 6：四個聚合閘之 checker / provider 註冊後回傳正確值。"""

    async def test_四閘皆已註冊(self, db, et_registered) -> None:
        assert module_assign_registry.get("ET") is not None
        # 未註冊之模組一律 fail-closed，故以「查得到且行為正確」驗證註冊成功
        assert await module_role_gate.has_any_role("ET", "ET_REG_NONE", db) is False

    async def test_is_module_admin_僅對管理者為真(self, db, et_registered) -> None:
        await _grant(db, "ET_REG_ADMIN", ROLE_ADMIN)
        await _grant(db, "ET_REG_TEACHER", ROLE_TEACHER)
        assert await module_admin_gate.is_module_admin("ET", "ET_REG_ADMIN", db) is True
        assert await module_admin_gate.is_module_admin("ET", "ET_REG_TEACHER", db) is False

    async def test_has_any_role_對任一角色為真(self, db, et_registered) -> None:
        await _grant(db, "ET_REG_ANY", ROLE_STUDENT)
        assert await module_role_gate.has_any_role("ET", "ET_REG_ANY", db) is True
        assert await module_role_gate.has_any_role("ET", "ET_REG_ABSENT", db) is False


class TestDefaultRoleProvisioning:
    """SRVET002：帳號建立當下授予學員角色（DP activation.py 已接線）。"""

    async def test_授予學員角色(self, db, et_registered) -> None:
        await grant_default_student_role(db, "ET_PROV_U1")
        assert await load_et_roles(db, "ET_PROV_U1") == frozenset({ROLE_STUDENT})

    async def test_冪等_重複呼叫不重複寫入(self, db, et_registered) -> None:
        """重寄驗證信 / 重寄邀請等情境會重複觸發，不得因唯一約束炸掉。"""
        await grant_default_student_role(db, "ET_PROV_U2")
        await grant_default_student_role(db, "ET_PROV_U2")
        assert await load_et_roles(db, "ET_PROV_U2") == frozenset({ROLE_STUDENT})

    async def test_經聚合閘呼叫亦生效(self, db, et_registered) -> None:
        await module_provisioning_gate.grant_default_role("ET", "ET_PROV_U3", db)
        assert await load_et_roles(db, "ET_PROV_U3") == frozenset({ROLE_STUDENT})
