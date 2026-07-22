"""US2 自助註冊（#56 方案 B）整合測試：檢核分流 / 寫待驗證表 + 寄驗證信（**不建 DP_USER**）。"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.notify.models import DpEmailLog
from app.dp.user.models import DpPendingRegistration, DpPwdHistory
from app.dp.user.register_service import RegisterService
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


async def test_register_writes_pending_not_user(client, db, et_stub):
    """合規註冊 → 202、寫待驗證列 + 寄驗證信；**不建 DP_USER、不授角色、不記稽核 / 歷程**（方案 B）。"""
    r = await client.post("/api/register", json=_payload(email="ok@edms.local"))
    assert r.status_code == 202

    # 待驗證列已寫、DP_USER 未建
    pending = (
        await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "ok@edms.local"))
    ).scalar_one()
    assert pending.user_name == "新學員" and len(pending.token_hash) == 64
    assert (await db.execute(select(DpUser).where(DpUser.email == "ok@edms.local"))).scalar_one_or_none() is None

    # 已排入驗證信 outbox（ACCOUNT_VERIFY）
    mail = (await db.execute(select(DpEmailLog).where(DpEmailLog.recipient == "ok@edms.local"))).scalar_one()
    assert mail.template_code == "ACCOUNT_VERIFY" and mail.status == "PENDING"

    # 未授角色 / 未寫稽核 / 未寫歷程（皆移至驗證步）
    assert et_stub == []
    assert (await db.execute(select(DpPwdHistory))).first() is None
    assert (await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-REGISTER"))).first() is None


async def test_register_duplicate_verified_email_409(db, et_stub):
    """Email 已被「已驗證帳號」佔用 → 409 DP_USER_001。"""
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


async def test_register_password_mismatch(db):
    """兩次密碼不一致 → 422 DP_USER_002（伺服器端）。"""
    with pytest.raises(AppError) as exc:
        await RegisterService().register(
            db, email="mm@edms.local", user_name="不一致", password=_GOOD_PWD, confirm_password="Zzzz9999"
        )
    assert exc.value.status_code == 422 and exc.value.error_code == "DP_USER_002"


async def test_register_weak_password(db):
    """密碼不符複雜度 → 422（DP_PWD_001/002）。"""
    with pytest.raises(AppError) as exc:
        await RegisterService().register(
            db, email="weak@edms.local", user_name="弱密碼", password="abc", confirm_password="abc"
        )
    assert exc.value.status_code == 422 and exc.value.error_code.startswith("DP_PWD_")


async def test_reregister_pending_replaces_row(db):
    """同 Email 於未驗證期間再次註冊 → 覆蓋待驗證列（單一列、token 換新），非 409。"""
    await RegisterService().register(
        db, email="again@edms.local", user_name="第一次", password=_GOOD_PWD, confirm_password=_GOOD_PWD
    )
    first = (
        await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "again@edms.local"))
    ).scalar_one()
    first_token = first.token_hash

    await RegisterService().register(
        db, email="again@edms.local", user_name="第二次", password=_GOOD_PWD, confirm_password=_GOOD_PWD
    )
    rows = (
        (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "again@edms.local")))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # 仍單一列（EMAIL 唯一、覆蓋）
    assert rows[0].token_hash != first_token  # 舊 token 已作廢、換新
    assert rows[0].user_name == "第二次"
