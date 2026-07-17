"""US1 入口頁模組摘要（T025）整合測試：ET 恆可用 / DM has_any_role 聚合 / 認證 + 強制變更閘。"""

from datetime import timedelta

import pytest

from app.core.auth import create_access_token
from app.core.module_roles import module_role_gate
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_URL = "/api/dp/user/module-summary"


async def _make_user(db, *, user_id, must_change=False, pwd_changed_days_ago=1):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=f"{user_id}@edms.local",
        pwd_hash=hash_password("Abcd1234"),
        user_name="入口測試",
        status="ACTIVE",
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=pwd_changed_days_ago),
        must_change_pwd=must_change,
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


def _bearer(user_id):
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def test_module_summary_default_dm_not_provisioned(client, db):
    """未接線模組 → ET 恆可用 True、DM 未開通 False。"""
    await _make_user(db, user_id="s1")
    r = await client.get(_URL, headers=_bearer("s1"))
    assert r.status_code == 200
    body = r.json()
    assert body["et"]["has_role"] is True
    assert body["dm"]["has_role"] is False


async def test_module_summary_dm_has_role(client, db):
    """DM 模組註冊 has_any_role 回 True → DM 卡可進入。"""
    await _make_user(db, user_id="s2")

    async def _dm_stub(_db, _user_id):
        return True

    module_role_gate.register("DM", _dm_stub)
    try:
        r = await client.get(_URL, headers=_bearer("s2"))
    finally:
        module_role_gate.unregister("DM")
    assert r.status_code == 200 and r.json()["dm"]["has_role"] is True


async def test_module_summary_requires_token(client):
    """未帶 token → 401 DP_AUTH_002。"""
    r = await client.get(_URL)
    assert r.status_code == 401 and r.json()["error_code"] == "DP_AUTH_002"


async def test_module_summary_blocked_when_must_change(client, db):
    """須變更密碼者 → 403 DP_AUTH_009（強制變更閘攔於入口頁前）。"""
    await _make_user(db, user_id="mc", must_change=True)
    r = await client.get(_URL, headers=_bearer("mc"))
    assert r.status_code == 403 and r.json()["error_code"] == "DP_AUTH_009"
