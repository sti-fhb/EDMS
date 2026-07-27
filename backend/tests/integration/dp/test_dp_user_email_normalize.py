"""#35 email 大小寫正規化 — 端到端整合測試（需經 HTTP 層才會觸發 schema 正規化）。

驗「混大小寫輸入 → schema 正規化成小寫 → 命中小寫儲存的帳號 / 存成小寫」。
直接呼叫 service（傳 str）不會過 schema，故一律走 `client`。
"""

import pytest
from sqlalchemy import select

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"


async def _make_user(db, *, email, password=_PWD, fail_count=0):
    now = utcnow()
    db.add(
        DpUser(
            user_id=email.split("@")[0][:20],
            email=email,
            pwd_hash=hash_password(password),
            user_name="測試員",
            status="ACTIVE",
            login_fail_count=fail_count,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def test_login_mixed_case_email_finds_lowercase_account(client, db):
    """登入以混大小寫 email + 正確密碼 → 正規化後命中小寫儲存的帳號（200）。"""
    await _make_user(db, email="user@edms.local")
    resp = await client.post("/api/login", json={"email": "  User@EDMS.Local  ", "password": _PWD})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_register_stores_email_lowercased(client, db):
    """註冊以混大小寫 email → 待驗證列以小寫儲存（正規化一致，日後登入查得到）。"""
    resp = await client.post(
        "/api/register",
        json={
            "email": "Mixed.Case@Example.COM",
            "user_name": "王小明",
            "password": _PWD,
            "confirm_password": _PWD,
        },
    )
    assert resp.status_code == 202
    # 以小寫查得到（證明存成小寫）；原大小寫查不到
    assert await AuthRepository().get_pending_by_email(db, "mixed.case@example.com") is not None
    assert await AuthRepository().get_pending_by_email(db, "Mixed.Case@Example.COM") is None


async def test_register_then_duplicate_mixed_case_rejected(client, db):
    """先以小寫建帳號，再以混大小寫變體註冊同 email → 正規化後撞既有 → 409（不會建出兩個帳號）。"""
    await _make_user(db, email="dup@edms.local")
    resp = await client.post(
        "/api/register",
        json={"email": "DUP@edms.local", "user_name": "重複", "password": _PWD, "confirm_password": _PWD},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "DP_USER_001"


async def test_mixed_case_login_failure_hits_same_account_lockout(client, db):
    """AC4 限流/鎖定面：混大小寫 email 的登入失敗計入**同一帳號**的失敗桶（正規化收斂）。

    門檻 5：seed fail_count=4，再以混大小寫變體 + 錯密碼登入一次 → 計入小寫帳號 → 達門檻鎖定。
    證明大小寫變體不會各算各的（否則永遠鎖不了）。
    """
    await _make_user(db, email="lockme@edms.local", fail_count=4)
    resp = await client.post("/api/login", json={"email": "LockMe@EDMS.Local", "password": "WrongPass9"})
    assert resp.status_code in (401, 403)  # 認證失敗（第 5 次）
    user = (await db.execute(select(DpUser).where(DpUser.email == "lockme@edms.local"))).scalar_one()
    assert user.login_fail_count == 5  # 計入同一帳號（非變體各算各的）
    assert user.locked_until is not None  # 達門檻鎖定
