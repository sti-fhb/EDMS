"""DM 模組角色判定閘註冊整合測試（§4 has_any_role / §1 is_module_admin）。

驗證 DM 於啟動時把 checker 註冊進 `module_role_gate` / `module_admin_gate` 後，
DP 入口頁 / 後台端點經閘可正確判定 DM 角色（查 `DM_USER_ROLE`）。
"""

import pytest

from app.core.module_admin import module_admin_gate
from app.core.module_roles import module_role_gate
from app.core.utils import utcnow
from app.dm.bootstrap import register_dm_module
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR
from app.dm.roles.models import DmUserRole

pytestmark = pytest.mark.integration


async def _grant(db, user_id: str, role_code: str) -> None:
    db.add(DmUserRole(user_id=user_id, role_code=role_code, created_user=user_id, created_date=utcnow()))
    await db.flush()


async def test_has_any_role_true_for_dm_user(db):
    """具任一 DM 角色 → 閘回 True（可進入 DM）。"""
    register_dm_module()
    await _grant(db, "GATE_R1", DM_EDITOR)
    assert await module_role_gate.has_any_role("DM", "GATE_R1", db) is True


async def test_has_any_role_false_for_non_dm_user(db):
    """無任何 DM 角色 → 閘回 False（未開通）。"""
    register_dm_module()
    assert await module_role_gate.has_any_role("DM", "GATE_NONE", db) is False


async def test_is_module_admin_true_only_for_admin(db):
    """DM_ADMIN → is_module_admin True；其他 DM 角色 → False。"""
    register_dm_module()
    await _grant(db, "GATE_ADMIN", DM_ADMIN)
    await _grant(db, "GATE_ED", DM_EDITOR)
    assert await module_admin_gate.is_module_admin("DM", "GATE_ADMIN", db) is True
    assert await module_admin_gate.is_module_admin("DM", "GATE_ED", db) is False
