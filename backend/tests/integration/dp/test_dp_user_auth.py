"""US1 登入 SRVDP（T021）整合測試：帳密驗證 / 鎖定狀態機 / 稽核（真實 DB + 種子參數）。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import decode_access_token
from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.service import AuthService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(
    db,
    *,
    email="u1@edms.local",
    password="Abcd1234",
    status="ACTIVE",
    fail_count=0,
    locked_until=None,
    must_change=False,
    pwd_changed_days_ago=1,
):
    now = utcnow()
    user = DpUser(
        user_id=email.split("@")[0],
        email=email,
        pwd_hash=hash_password(password),
        user_name="測試員",
        status=status,
        login_fail_count=fail_count,
        locked_until=locked_until,
        pwd_changed_date=now - timedelta(days=pwd_changed_days_ago),
        must_change_pwd=must_change,
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


async def _audit_rows(db):
    result = await db.execute(select(DpAuditLog).order_by(DpAuditLog.log_id))
    return list(result.scalars().all())


async def test_login_success(db):
    """正確帳密 → 回 token（可解碼 sub）、must_change_pwd False、重設計數、更新 last_login、寫 LOGIN 稽核。"""
    await _make_user(db, email="ok@edms.local", password="Abcd1234", fail_count=2)
    result = await AuthService().login(db, email="ok@edms.local", password="Abcd1234")
    assert decode_access_token(result.access_token).sub == "ok"
    assert result.must_change_pwd is False
    user = (await db.execute(select(DpUser).where(DpUser.email == "ok@edms.local"))).scalar_one()
    assert user.login_fail_count == 0 and user.last_login_date is not None
    audit = [a for a in await _audit_rows(db) if a.action_type == "LOGIN"]
    assert audit and audit[-1].result == "SUCCESS"


async def test_login_no_account(db):
    """帳號不存在 → DP_AUTH_007。"""
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email="ghost@edms.local", password="x")
    assert exc.value.status_code == 401 and exc.value.error_code == "DP_AUTH_007"


async def test_login_wrong_password(db):
    """密碼錯誤 → DP_AUTH_008、失敗計數 +1。"""
    await _make_user(db, email="wp@edms.local", password="Abcd1234")
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email="wp@edms.local", password="wrong")
    assert exc.value.error_code == "DP_AUTH_008"
    user = (await db.execute(select(DpUser).where(DpUser.email == "wp@edms.local"))).scalar_one()
    assert user.login_fail_count == 1


async def test_login_locks_after_max_fails(db):
    """連續失敗達 FAIL_LOCK_COUNT（種子 5）→ 自動鎖定；再登入 → DP_AUTH_005。"""
    await _make_user(db, email="lock@edms.local", password="Abcd1234", fail_count=4)
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email="lock@edms.local", password="wrong")  # 第 5 次失敗
    assert exc.value.error_code == "DP_AUTH_008"
    user = (await db.execute(select(DpUser).where(DpUser.email == "lock@edms.local"))).scalar_one()
    assert user.login_fail_count == 5 and user.locked_until is not None
    # 鎖定後即使密碼正確也拒
    with pytest.raises(AppError) as exc2:
        await AuthService().login(db, email="lock@edms.local", password="Abcd1234")
    assert exc2.value.status_code == 403 and exc2.value.error_code == "DP_AUTH_005"


async def test_login_lock_expired_auto_unlock(db):
    """LOCKED_UNTIL 已過 → 視為解鎖，正確密碼可登入。"""
    await _make_user(
        db, email="exp@edms.local", password="Abcd1234", fail_count=5, locked_until=utcnow() - timedelta(minutes=1)
    )
    result = await AuthService().login(db, email="exp@edms.local", password="Abcd1234")
    assert result.access_token
    user = (await db.execute(select(DpUser).where(DpUser.email == "exp@edms.local"))).scalar_one()
    assert user.login_fail_count == 0


async def test_login_disabled_rejected(db):
    """STATUS=DISABLED → DP_AUTH_004。"""
    await _make_user(db, email="dis@edms.local", password="Abcd1234", status="DISABLED")
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email="dis@edms.local", password="Abcd1234")
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_AUTH_004"


async def test_login_must_change_pwd_flag(db):
    """MUST_CHANGE_PWD=true → 登入成功但 must_change_pwd True。"""
    await _make_user(db, email="mc@edms.local", password="Abcd1234", must_change=True)
    result = await AuthService().login(db, email="mc@edms.local", password="Abcd1234")
    assert result.must_change_pwd is True


async def test_login_pwd_expired_flag(db):
    """密碼逾效期（種子 EXPIRY_DAYS=90）→ must_change_pwd True。"""
    await _make_user(db, email="old@edms.local", password="Abcd1234", pwd_changed_days_ago=91)
    result = await AuthService().login(db, email="old@edms.local", password="Abcd1234")
    assert result.must_change_pwd is True


async def test_login_wrong_password_persists_through_request(client, db):
    """回歸：經真實端點（get_db 對 AppError rollback）打錯密碼後，失敗計數與 FAIL 稽核仍須落地。

    修正前：service 在同交易 flush 後 raise，get_db rollback 抹除計數 → 鎖定機制形同虛設。
    """
    await _make_user(db, email="ep@edms.local", password="Abcd1234")
    r = await client.post("/api/login", json={"email": "ep@edms.local", "password": "WRONG"})
    assert r.status_code == 401 and r.json()["error_code"] == "DP_AUTH_008"
    user = (await db.execute(select(DpUser).where(DpUser.email == "ep@edms.local"))).scalar_one()
    assert user.login_fail_count == 1  # 未被請求層 rollback 抹除
    fail_audit = [a for a in await _audit_rows(db) if a.action_type == "LOGIN" and a.result == "FAIL"]
    assert fail_audit and fail_audit[-1].description == "密碼錯誤"


async def test_login_success_through_request(client, db):
    """回歸：經真實端點成功登入回 200 + token，且計數重設 / last_login 落地。"""
    await _make_user(db, email="eps@edms.local", password="Abcd1234", fail_count=2)
    r = await client.post("/api/login", json={"email": "eps@edms.local", "password": "Abcd1234"})
    assert r.status_code == 200
    body = r.json()
    assert decode_access_token(body["access_token"]).sub == "eps" and body["must_change_pwd"] is False
    user = (await db.execute(select(DpUser).where(DpUser.email == "eps@edms.local"))).scalar_one()
    assert user.login_fail_count == 0 and user.last_login_date is not None
