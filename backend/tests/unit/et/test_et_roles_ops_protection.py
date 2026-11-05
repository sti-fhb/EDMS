"""廠商維運帳號（`edmsops`）之 ET 預設角色保護單元測試（#927）。"""

import pytest

from app.core.exceptions import AppError
from app.core.ops_account import OPS_USER_ID
from app.et.constants import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER
from app.et.roles.assign_service import ensure_ops_default_roles_kept

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("roles", [set(), {ROLE_TEACHER, ROLE_STUDENT}])
def test_ops_account_without_admin_blocked(roles):
    """維運帳號送出的角色集不含 ADMIN → 403 ET_ROLE_005。"""
    with pytest.raises(AppError) as e:
        ensure_ops_default_roles_kept(OPS_USER_ID, roles)
    assert e.value.error_code == "ET_ROLE_005" and e.value.status_code == 403


@pytest.mark.parametrize("roles", [{ROLE_ADMIN}, {ROLE_ADMIN, ROLE_TEACHER}])
def test_ops_account_keeping_admin_allowed(roles):
    """保留 ADMIN 即放行；另加的 TEACHER / STUDENT 可增可減。"""
    ensure_ops_default_roles_kept(OPS_USER_ID, roles)


def test_other_account_losing_admin_allowed():
    """對照：一般帳號拿掉 ADMIN 不受此規則限制。"""
    ensure_ops_default_roles_kept("U0000001", {ROLE_STUDENT})
