"""US1 換發 / 登出（T022）整合測試：單日換發上限、狀態閘、登出稽核（真實 DB + 種子參數）。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token, decode_access_token
from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.service import AuthService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, *, user_id="ru", email="ru@edms.local", status="ACTIVE"):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email,
        pwd_hash=hash_password("Abcd1234"),
        user_name="換發測試",
        status=status,
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=1),
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


def _bearer(user_id, *, auth_time=None):
    token = create_access_token(sub=user_id, ttl_minutes=15, auth_time=auth_time)
    return {"Authorization": f"Bearer {token}"}


# --- service 層：換發上限邏輯（純邏輯 + DP_PARAM 讀取）---


async def test_renew_success_preserves_auth_time(db):
    """換發成功：沿用原 auth_time、sub 不變、回新 token。"""
    old_auth = utcnow() - timedelta(hours=2)
    payload = decode_access_token(create_access_token(sub="u1", ttl_minutes=15, auth_time=old_auth))
    result = await AuthService().renew(db, payload=payload)
    new_payload = decode_access_token(result.access_token)
    assert new_payload.sub == "u1"
    assert int(new_payload.auth_time.timestamp()) == int(old_auth.timestamp())  # 沿用原登入時間


async def test_renew_over_limit_rejected(db):
    """距 auth_time 逾單日換發上限（種子 8h）→ DP_AUTH_003。"""
    old_auth = utcnow() - timedelta(hours=9)
    payload = decode_access_token(create_access_token(sub="u1", ttl_minutes=15, auth_time=old_auth))
    with pytest.raises(AppError) as exc:
        await AuthService().renew(db, payload=payload)
    assert exc.value.status_code == 401 and exc.value.error_code == "DP_AUTH_003"


# --- 端點層：狀態閘 wiring + 登出稽核 ---


async def test_renew_endpoint_success(client, db):
    """有效 token 且未逾限 → 200 回新 token。"""
    await _make_user(db, user_id="ok", email="ok@edms.local")
    r = await client.post("/api/dp/user/renew", headers=_bearer("ok", auth_time=utcnow() - timedelta(hours=1)))
    assert r.status_code == 200 and decode_access_token(r.json()["access_token"]).sub == "ok"


async def test_renew_endpoint_requires_token(client):
    """未帶 token → 401 DP_AUTH_002（get_jwt_payload 認證閘）。"""
    r = await client.post("/api/dp/user/renew")
    assert r.status_code == 401 and r.json()["error_code"] == "DP_AUTH_002"


async def test_renew_endpoint_disabled_gated(client, db):
    """停用帳號的 token 換發 → 403 DP_AUTH_004（每請求 DP_USER 狀態閘）。"""
    await _make_user(db, user_id="dis", email="dis@edms.local", status="DISABLED")
    r = await client.post("/api/dp/user/renew", headers=_bearer("dis"))
    assert r.status_code == 403 and r.json()["error_code"] == "DP_AUTH_004"


async def test_logout_endpoint_writes_audit(client, db):
    """登出 → 204，且寫 LOGOUT SUCCESS 稽核（操作者為登出者）。"""
    await _make_user(db, user_id="bye", email="bye@edms.local")
    r = await client.post("/api/dp/user/logout", headers=_bearer("bye"))
    assert r.status_code == 204
    rows = (await db.execute(select(DpAuditLog).where(DpAuditLog.action_type == "LOGOUT"))).scalars().all()
    assert rows and rows[-1].result == "SUCCESS" and rows[-1].created_user == "bye"
