"""US2 自助註冊（#56 方案 B）整合測試：檢核分流 / 寫待驗證表 + 寄驗證信（**不建 DP_USER**）。"""

from datetime import timedelta

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
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


def _payload(**over):
    base = {
        "email": "newbie@edms.local",
        "user_name": "新學員",
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
        await RegisterService().register(db, email="dup@edms.local", user_name="重複")
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_001"


async def test_reregister_pending_replaces_row(db):
    """同 Email 於未驗證期間再次註冊 → 覆蓋待驗證列（單一列、token 換新），非 409。"""
    await RegisterService().register(db, email="again@edms.local", user_name="第一次")
    first = (
        await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "again@edms.local"))
    ).scalar_one()
    first_token = first.token_hash

    await RegisterService().register(db, email="again@edms.local", user_name="第二次")
    rows = (
        (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "again@edms.local")))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # 仍單一列（EMAIL 唯一、覆蓋）
    assert rows[0].token_hash != first_token  # 舊 token 已作廢、換新
    assert rows[0].user_name == "第二次"


# ---- #125：自助註冊不得靜默覆蓋管理者邀請 ----


async def _make_admin_invite(db, email: str, *, minutes: int):
    """建一筆 ADMIN_INVITE 待啟用列；minutes 為負代表已逾期。回傳其 token_hash。"""
    now = utcnow()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=hash_token(f"invite-token-{email}"),
        email=email,
        user_name="受邀者",
        pwd_hash=None,
        expires_date=now + timedelta(minutes=minutes),
        now=now,
        kind="ADMIN_INVITE",
        invite_id="u-invited-001",
        operator_id="admin01",
    )
    await db.flush()
    return hash_token(f"invite-token-{email}")


async def test_register_blocked_by_unexpired_admin_invite(db):
    """#125 AC1/AC2：未逾期的管理者邀請 → 409 DP_USER_011，且邀請列完全未被覆蓋。"""
    email = "invited@edms.local"
    original_token = await _make_admin_invite(db, email, minutes=30)

    with pytest.raises(AppError) as exc:
        await RegisterService().register(db, email=email, user_name="想自己註冊")
    assert exc.value.status_code == 409
    assert exc.value.error_code == "DP_USER_011"

    # 邀請列原封不動：token 未換（原邀請連結仍可用）、kind / 姓名未被覆蓋
    row = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == email))).scalar_one()
    assert row.token_hash == original_token
    assert row.kind == "ADMIN_INVITE"
    assert row.user_name == "受邀者"
    assert row.pwd_hash is None


async def test_register_overwrites_expired_admin_invite(db, et_stub):
    """#125 AC3：已逾期的管理者邀請不應永久卡住該 Email → 允許註冊並覆蓋。"""
    email = "expired-invite@edms.local"
    original_token = await _make_admin_invite(db, email, minutes=-1)

    await RegisterService().register(db, email=email, user_name="自己註冊")

    row = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == email))).scalar_one()
    assert row.token_hash != original_token  # 舊邀請 token 已作廢
    assert row.kind == "SELF_REGISTER"
    assert row.user_name == "自己註冊"
    assert row.pwd_hash is None  # #212：pending 列不存密碼，密碼於驗證步當場設定


async def test_delete_pending_unless_active_invite_keeps_valid_invite(db):
    """#125 TOCTOU 安全網：條件式刪除保留有效邀請、清掉其餘（自助註冊列與逾期邀請）。

    直測 repository：register_service 的前置檢查與刪除之間有空窗，若該空窗內管理者剛好
    發出邀請，無條件刪除會靜默吃掉它。此方法確保有效邀請存活，後續 insert 撞 UNIQUE。
    """
    repo = AuthRepository()
    now = utcnow()

    await _make_admin_invite(db, "keep@edms.local", minutes=30)  # 有效邀請 → 應保留
    await _make_admin_invite(db, "drop-expired@edms.local", minutes=-1)  # 逾期邀請 → 應刪除
    await repo.create_pending_registration(  # 自助註冊列 → 應刪除
        db,
        token_hash=hash_token("self-token"),
        email="drop-self@edms.local",
        user_name="自助",
        pwd_hash=hash_password(_GOOD_PWD),
        expires_date=now + timedelta(minutes=30),
        now=now,
    )
    await db.flush()

    for email in ("keep@edms.local", "drop-expired@edms.local", "drop-self@edms.local"):
        await repo.delete_pending_unless_active_invite(db, email, utcnow())
    await db.flush()

    remaining = {
        r.email
        for r in (
            (
                await db.execute(
                    select(DpPendingRegistration).where(
                        DpPendingRegistration.email.in_(
                            ["keep@edms.local", "drop-expired@edms.local", "drop-self@edms.local"]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    assert remaining == {"keep@edms.local"}


async def test_overwriting_expired_invite_writes_audit(db, et_stub):
    """#125：覆蓋逾期管理者邀請時須留稽核，否則管理者查不到邀請為何消失。

    覆蓋本身是預期行為（AC3），但該列由管理者建立、其建立與取消皆有稽核；
    若被匿名註冊無痕抹除，稽核就出現斷點。
    """
    email = "audited-expired@edms.local"
    await _make_admin_invite(db, email, minutes=-1)

    await RegisterService().register(db, email=email, user_name="自己註冊")

    log = (
        await db.execute(
            select(DpAuditLog).where(DpAuditLog.target_id == "u-invited-001", DpAuditLog.action_type == "DELETE")
        )
    ).scalar_one()
    assert log.func_name == "DP-REGISTER"
    assert log.created_user == "SYSTEM"  # 匿名註冊者無 user_id，非管理者所為
    assert "逾期管理者邀請被自助註冊覆蓋" in log.description
    assert "ADMIN_INVITE" in log.before_value  # 前值留下被覆蓋掉的邀請樣貌


async def test_self_register_overwrite_writes_audit(db, et_stub):
    """覆蓋既有自助註冊列 → 記一筆 DELETE 稽核（#212）。

    修法 B 之後覆蓋已不構成帳號接管（列裡沒有密碼），但它仍會作廢他人仍有效的驗證連結並
    換掉姓名——使用者只會發現連結突然失效，客服需查得到原因。

    因此 target_id 記 Email：稽核查詢只能按 target_id 篩、不支援 before_value 關鍵字搜尋，
    把 Email 只留在 JSON 裡等於這列實務上查不到。本斷言即釘住「這列查得到」。
    """
    email = "plain-overwrite@edms.local"
    await RegisterService().register(db, email=email, user_name="第一次")
    before = len((await db.execute(select(DpAuditLog))).scalars().all())

    await RegisterService().register(db, email=email, user_name="第二次")
    logs = (await db.execute(select(DpAuditLog))).scalars().all()
    assert len(logs) == before + 1

    log = logs[-1]
    assert log.action_type == "DELETE" and log.result == "SUCCESS"
    assert "既有自助註冊申請被新的註冊申請覆蓋" in log.description
    assert "第一次" in log.before_value and email in log.before_value
    assert log.target_id == email  # 可經稽核查詢的 target 維度找到
