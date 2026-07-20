"""US2 自助註冊（T026）整合測試：檢核分流 / 建帳號 + 首筆歷程 + 授 ET 學員 + 雙稽核。"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_policy import hash_password, verify_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.models import DpPwdHistory
from app.dp.user.register_service import RegisterService
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


def _payload(**over):
    base = {
        "email": "newbie@edms.local",
        "user_name": "新學員",
        "password": _GOOD_PWD,
        "confirm_password": _GOOD_PWD,
    }
    base.update(over)
    return base


@pytest.fixture
def et_stub():
    """註冊 ET 預設角色授予 stub（記錄被授予的 user_id），測試後移除。"""
    granted: list[str] = []

    async def _grant(_db, user_id):
        granted.append(user_id)

    module_provisioning_gate.register("ET", _grant)
    yield granted
    module_provisioning_gate.unregister("ET")


async def test_register_success_via_endpoint(client, db, et_stub):
    """未註冊 Email + 合規密碼 → 201、建 ACTIVE 帳號（bcrypt）、首筆歷程、授 ET 學員、雙稽核落地。"""
    r = await client.post("/api/register", json=_payload(email="ok@edms.local"))
    assert r.status_code == 201

    user = (await db.execute(select(DpUser).where(DpUser.email == "ok@edms.local"))).scalar_one()
    assert user.status == "ACTIVE" and user.must_change_pwd is False
    assert verify_password(_GOOD_PWD, user.pwd_hash)  # bcrypt 雜湊、可驗
    assert user.created_user == user.user_id  # operator = 本人（Clarification）

    hist = (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == user.user_id))).scalars().all()
    assert len(hist) == 1 and hist[0].seq_no == 1 and hist[0].pwd_hash == user.pwd_hash

    assert et_stub == [user.user_id]  # 授予 ET 學員（僅此一次；未授任何 DM）

    audits = (
        (
            await db.execute(
                select(DpAuditLog).where(DpAuditLog.func_name == "DP-REGISTER", DpAuditLog.action_type == "CREATE")
            )
        )
        .scalars()
        .all()
    )
    descs = {a.description for a in audits}
    assert "使用者自助註冊" in descs and "授予預設 ET 學員角色" in descs
    assert all(a.created_user == user.user_id and a.module == "DP" for a in audits)


async def test_register_duplicate_email(db, et_stub):
    """Email 已被註冊 → 409 DP_USER_001。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id="existing1",
            email="dup@edms.local",
            pwd_hash=hash_password(_GOOD_PWD),
            user_name="既有",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()
    with pytest.raises(AppError) as exc:
        await RegisterService().register(
            db, email="dup@edms.local", user_name="重複", password=_GOOD_PWD, confirm_password=_GOOD_PWD
        )
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_001"


async def test_register_password_mismatch(db, et_stub):
    """兩次密碼不一致 → 422 DP_USER_002（伺服器端）。"""
    with pytest.raises(AppError) as exc:
        await RegisterService().register(
            db, email="mm@edms.local", user_name="不一致", password=_GOOD_PWD, confirm_password="Zzzz9999"
        )
    assert exc.value.status_code == 422 and exc.value.error_code == "DP_USER_002"


async def test_register_weak_password(db, et_stub):
    """密碼不符複雜度 → 422（DP_PWD_001/002）。"""
    with pytest.raises(AppError) as exc:
        await RegisterService().register(
            db, email="weak@edms.local", user_name="弱密碼", password="abc", confirm_password="abc"
        )
    assert exc.value.status_code == 422 and exc.value.error_code.startswith("DP_PWD_")


async def test_register_unprovisioned_module_noop(db):
    """ET 未註冊 granter（stub 未注入）→ no-op 不擋註冊，帳號仍建立成功。"""
    # 未使用 et_stub fixture：module_provisioning_gate 無 ET granter
    await RegisterService().register(
        db, email="noet@edms.local", user_name="無ET", password=_GOOD_PWD, confirm_password=_GOOD_PWD
    )
    user = (await db.execute(select(DpUser).where(DpUser.email == "noet@edms.local"))).scalar_one()
    assert user.status == "ACTIVE"


async def test_register_grant_failure_rolls_back(client, db):
    """已註冊 ET granter 拋例外 → 整筆交易回滾（帳號 / 歷程 / 稽核皆不落地），回 500。"""

    async def _boom(_db, _user_id):
        raise RuntimeError("ET service down")

    module_provisioning_gate.register("ET", _boom)
    try:
        r = await client.post("/api/register", json=_payload(email="rollback@edms.local"))
    finally:
        module_provisioning_gate.unregister("ET")
    assert r.status_code == 500  # granter 例外 → 通用 500（get_db rollback）
    # 整筆回滾：帳號 / 首筆歷程 / 稽核皆未落地
    assert (await db.execute(select(DpUser).where(DpUser.email == "rollback@edms.local"))).scalar_one_or_none() is None
    assert (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == "rollback"))).first() is None


async def test_register_email_race_maps_to_409(db, et_stub):
    """TOCTOU 競態：email_exists 檢查時不存在、寫入時已存在 → IntegrityError 轉乾淨 409（非 500）。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id="racer1",
            email="race@edms.local",
            pwd_hash=hash_password(_GOOD_PWD),
            user_name="既有",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()

    class _RaceRepo(AuthRepository):
        async def email_exists(self, _db, _email):
            return False  # 模擬檢查瞬間查無、寫入瞬間已被搶註

    with pytest.raises(AppError) as exc:
        await RegisterService(repository=_RaceRepo()).register(
            db, email="race@edms.local", user_name="競態", password=_GOOD_PWD, confirm_password=_GOOD_PWD
        )
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_001"
