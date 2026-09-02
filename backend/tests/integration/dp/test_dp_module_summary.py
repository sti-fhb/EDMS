"""US1 入口頁模組摘要（T025）整合測試：ET / DM 皆經 has_any_role 聚合 + 認證 / 強制變更閘。"""

from datetime import timedelta

import pytest

from app.core.auth import create_access_token
from app.core.module_admin import module_admin_gate
from app.core.module_roles import module_role_gate
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.roles.gate import dm_is_module_admin
from app.dp.users.models import DpUser

# teardown 還原用：ET 已於 main.py 註冊真實 checker，測試替換後須放回原樣（測試專用引用）
from app.et.roles.gate import et_has_any_role

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


async def test_module_summary_無任一模組角色時皆未開通(client, db):
    """無 ET / DM 角色者兩者皆 False。

    ET 原寫死 `True`（學員為預設角色、人人皆有），#185 接線後改為實查 `ET_USER_ROLE`
    ——管理者於 DP 後台**取消**某人之學員角色後，側欄須隨之隱藏，否則該群組點進去
    每個端點都被存取閘以 403 `ET_AUTH_001` 擋下（側欄承諾了存取閘不給的東西）。
    """
    await _make_user(db, user_id="s1")
    r = await client.get(_URL, headers=_bearer("s1"))
    assert r.status_code == 200
    body = r.json()
    assert body["et"]["has_role"] is False, "無任一 ET 角色者不應顯示 ET 側欄群組"
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


async def test_module_summary_et_has_role(client, db):
    """ET 模組 has_any_role 回 True → 側欄顯示「教育訓練」群組。

    以 stub 替換而非建真實 `ET_USER_ROLE` 列：本檔驗的是 **DP 的聚合行為**，ET 端
    checker 對 `ET_USER_ROLE` 的實際查詢由 `tests/integration/et/test_et_access_gate.py`
    覆蓋。teardown 還原 `main.py` 註冊之真實 checker（非 unregister——ET 已接線，
    移除會讓後續測試看到未接線狀態）。
    """
    await _make_user(db, user_id="s3")

    async def _et_stub(_db, _user_id):
        return True

    module_role_gate.register("ET", _et_stub)
    try:
        r = await client.get(_URL, headers=_bearer("s3"))
    finally:
        module_role_gate.register("ET", et_has_any_role)
    assert r.status_code == 200 and r.json()["et"]["has_role"] is True


async def test_module_summary_is_admin_預設為否(client, db):
    """無任一模組管理者角色者 `is_admin` 皆 False（側欄「系統管理者後台」群組據此隱藏，#250）。"""
    await _make_user(db, user_id="na1")
    r = await client.get(_URL, headers=_bearer("na1"))
    assert r.status_code == 200
    body = r.json()
    assert body["et"]["is_admin"] is False
    assert body["dm"]["is_admin"] is False


async def test_module_summary_is_admin_經管理者判定閘(client, db):
    """`is_admin` 經 `module_admin_gate` 判定；DM 管理者 → dm.is_admin=True、et 仍 False。

    teardown 還原 `main.py` 註冊之真實 checker（非 unregister——DM / ET 皆已接線，
    移除會讓後續測試看到未接線狀態，比照本檔 has_role 案例）。
    """
    await _make_user(db, user_id="dma")

    async def _dm_admin_stub(_db, _user_id):
        return True

    module_admin_gate.register("DM", _dm_admin_stub)
    try:
        r = await client.get(_URL, headers=_bearer("dma"))
    finally:
        module_admin_gate.register("DM", dm_is_module_admin)
    assert r.status_code == 200
    body = r.json()
    assert body["dm"]["is_admin"] is True, "DM 管理者應可見系統管理者後台"
    assert body["et"]["is_admin"] is False, "非 ET 管理者不應被誤判"


async def test_module_summary_requires_token(client):
    """未帶 token → 401 DP_AUTH_002。"""
    r = await client.get(_URL)
    assert r.status_code == 401 and r.json()["error_code"] == "DP_AUTH_002"


async def test_module_summary_blocked_when_must_change(client, db):
    """須變更密碼者 → 403 DP_AUTH_009（強制變更閘攔於入口頁前）。"""
    await _make_user(db, user_id="mc", must_change=True)
    r = await client.get(_URL, headers=_bearer("mc"))
    assert r.status_code == 403 and r.json()["error_code"] == "DP_AUTH_009"
