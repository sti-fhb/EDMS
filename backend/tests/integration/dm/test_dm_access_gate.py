"""DM 存取閘整合測試（重用 DP 認證後，以 DM_USER_ROLE 判准入）。"""

import pytest

from app.core.auth import JwtPayload
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.deps import DmContext, get_dm_context, load_dm_roles
from app.dm.roles.authz import DM_EDITOR
from app.dm.roles.models import DmUserRole

pytestmark = pytest.mark.integration


def _payload(user_id: str) -> JwtPayload:
    now = utcnow()
    return JwtPayload(sub=user_id, auth_time=now, iat=now, exp=now)


async def _grant(db, user_id: str, role_code: str) -> None:
    db.add(DmUserRole(user_id=user_id, role_code=role_code, created_user=user_id, created_date=utcnow()))
    await db.flush()


async def test_load_roles_returns_assigned(db):
    """load_dm_roles 回傳使用者已指派之 DM 角色集。"""
    await _grant(db, "GATE_U1", DM_EDITOR)
    roles = await load_dm_roles(db, "GATE_U1")
    assert roles == frozenset({DM_EDITOR})


async def test_gate_rejects_user_without_dm_role(db):
    """已認證但無任何 DM 角色 → 403 DM_AUTH_001。"""
    with pytest.raises(AppError) as e:
        await get_dm_context(payload=_payload("GATE_NONE"), db=db)
    assert e.value.status_code == 403
    assert e.value.error_code == "DM_AUTH_001"


async def test_gate_allows_user_with_dm_role(db):
    """具備任一 DM 角色 → 放行並帶回角色集。"""
    await _grant(db, "GATE_U2", DM_EDITOR)
    ctx = await get_dm_context(payload=_payload("GATE_U2"), db=db)
    assert isinstance(ctx, DmContext)
    assert ctx.user_id == "GATE_U2"
    assert DM_EDITOR in ctx.roles
