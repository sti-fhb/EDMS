"""認證閘 get_jwt_payload（T014）整合測試：每請求查 DP_USER 狀態（真實 DB）。"""

from datetime import timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import create_access_token, get_jwt_payload
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, user_id="user001", *, status="ACTIVE", locked_until=None, deleted=0):
    """建立測試用 DP_USER 並 flush。"""
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=f"{user_id}@edms.local",
        pwd_hash="x",
        user_name="測試員",
        status=status,
        locked_until=locked_until,
        pwd_changed_date=now,
        created_user="admin01",
        created_date=now,
        deleted=deleted,
    )
    db.add(user)
    await db.flush()
    return user


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_valid_token_active_user_passes(db):
    """有效 token + ACTIVE 使用者 → 回 payload。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)
    payload = await get_jwt_payload(credentials=_creds(token), db=db)
    assert payload.sub == "user001"


async def test_missing_credentials_rejected(db):
    """無 Authorization → 401 DP_AUTH_002。"""
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=None, db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"


async def test_invalid_token_rejected(db):
    """竄改 token → 401 DP_AUTH_002（decode 階段即拒，不查 DB）。"""
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token[:-2] + "xx"), db=db)
    assert exc.value.error_code == "DP_AUTH_002"


async def test_deleted_user_rejected(db):
    """token 有效但使用者已軟刪 → 401 DP_AUTH_002（session 失效）。"""
    await _make_user(db, "user001", deleted=1)
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"


async def test_unknown_user_rejected(db):
    """token 有效但 USER_ID 查無 → 401 DP_AUTH_002。"""
    token = create_access_token(sub="ghost", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.error_code == "DP_AUTH_002"


async def test_disabled_user_rejected(db):
    """STATUS=DISABLED → 403 DP_AUTH_004。"""
    await _make_user(db, "user001", status="DISABLED")
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_004"


async def test_locked_user_rejected(db):
    """LOCKED_UNTIL 在未來（鎖定中）→ 403 DP_AUTH_005。"""
    await _make_user(db, "user001", locked_until=utcnow() + timedelta(minutes=30))
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_005"


async def test_expired_lock_passes(db):
    """LOCKED_UNTIL 已過（自動解鎖）→ 通過。"""
    await _make_user(db, "user001", locked_until=utcnow() - timedelta(minutes=1))
    token = create_access_token(sub="user001", ttl_minutes=15)
    payload = await get_jwt_payload(credentials=_creds(token), db=db)
    assert payload.sub == "user001"
