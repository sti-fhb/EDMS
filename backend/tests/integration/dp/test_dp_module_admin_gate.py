"""模組管理者判定閘（T017）整合測試：require_module_admin dependency（真實 DB）。"""

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate, require_module_admin
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, user_id="user001"):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash="x",
            user_name="測試員",
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


async def _get_payload(creds, db):
    from app.core.auth import get_jwt_payload

    return await get_jwt_payload(credentials=creds, db=db)


async def _always(_db, _user_id):
    return True


async def _never(_db, _user_id):
    return False


async def test_require_admin_allows(db):
    """已註冊 checker 判定為管理者 → 通過並回 payload。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)
    module_admin_gate.register("ET", _always)
    try:
        dep = require_module_admin("ET")
        payload = await _get_payload(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        result = await dep(payload=payload, db=db)
        assert result.sub == "user001"
    finally:
        module_admin_gate.unregister("ET")


async def test_require_admin_denies_non_admin(db):
    """checker 判定為非管理者 → 403 DP_AUTH_006。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)
    module_admin_gate.register("ET", _never)
    try:
        dep = require_module_admin("ET")
        payload = await _get_payload(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        with pytest.raises(AppError) as exc:
            await dep(payload=payload, db=db)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "DP_AUTH_006"
    finally:
        module_admin_gate.unregister("ET")


async def test_require_admin_denies_on_checker_exception(db):
    """checker 拋例外 → fail-closed 403 DP_AUTH_006（不傳播成 500）。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)

    async def _boom(_db, _user_id):
        raise RuntimeError("boom")

    module_admin_gate.register("ET", _boom)
    try:
        dep = require_module_admin("ET")
        payload = await _get_payload(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        with pytest.raises(AppError) as exc:
            await dep(payload=payload, db=db)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "DP_AUTH_006"
    finally:
        module_admin_gate.unregister("ET")


async def test_require_admin_denies_unregistered(db):
    """未註冊模組 → fail-closed 403。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)
    module_admin_gate.unregister("ET")  # 確保未註冊
    dep = require_module_admin("ET")
    payload = await _get_payload(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
    with pytest.raises(AppError) as exc:
        await dep(payload=payload, db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_006"
