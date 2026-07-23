"""US2 註冊驗證 / 重寄（#56 方案 B）整合測試：verify → 建 DP_USER + 啟用副作用 + 刪待驗證列；
未驗證登入專屬提示；resend 換新 token；驗證冪等。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.models import DpPendingRegistration, DpPwdHistory
from app.dp.user.service import AuthService
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.user.verify_service import ResendVerificationService, VerifyService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


@pytest.fixture
def et_stub():
    granted: list[str] = []

    async def _grant(_db, user_id):
        granted.append(user_id)

    module_provisioning_gate.register("ET", _grant)
    yield granted
    module_provisioning_gate.unregister("ET")


async def _seed_pending(db, *, email: str, minutes: int = 30, plaintext: str | None = None) -> str:
    """直接建一筆待驗證列（以已知明文 token），回傳明文供 verify。"""
    plaintext = plaintext or generate_reset_token()
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token(plaintext),
            email=email,
            user_name="待驗證",
            pwd_hash=hash_password(_GOOD_PWD),
            kind="SELF_REGISTER",
            expires_date=now + timedelta(minutes=minutes),
            created_user="SYSTEM",
            created_date=now,
        )
    )
    await db.flush()
    return plaintext


async def test_verify_activates_user(db, et_stub):
    """有效 token → 建 DP_USER(ACTIVE) + 授 ET 學員 + 雙稽核 + 首筆歷程 + 刪待驗證列。"""
    token = await _seed_pending(db, email="verify@edms.local")
    await VerifyService().verify(db, token=token)

    user = (await db.execute(select(DpUser).where(DpUser.email == "verify@edms.local"))).scalar_one()
    assert user.status == "ACTIVE" and user.created_user == user.user_id
    assert et_stub == [user.user_id]  # 授 ET 學員

    hist = (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == user.user_id))).scalars().all()
    assert len(hist) == 1 and hist[0].seq_no == 1

    audits = (await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-REGISTER"))).scalars().all()
    assert {a.description for a in audits} >= {"授予預設 ET 學員角色"}
    assert all(a.created_user == user.user_id for a in audits)

    # 待驗證列已消費
    assert (
        await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "verify@edms.local"))
    ).scalar_one_or_none() is None


async def test_verify_invalid_token(db, et_stub):
    """token 不存在 → 400 DP_USER_003。"""
    with pytest.raises(AppError) as exc:
        await VerifyService().verify(db, token="nonexistent-token")
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_USER_003"


async def test_verify_expired_token(db, et_stub):
    """token 逾時 → 400 DP_USER_004；不建 DP_USER。"""
    token = await _seed_pending(db, email="expired@edms.local", minutes=-1)
    with pytest.raises(AppError) as exc:
        await VerifyService().verify(db, token=token)
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_USER_004"
    assert (await db.execute(select(DpUser).where(DpUser.email == "expired@edms.local"))).scalar_one_or_none() is None


async def test_verify_idempotent_when_already_verified(db, et_stub):
    """Email 已存在於 DP_USER（已驗證 / 競態）→ 建帳撞唯一鍵 → 409 DP_USER_001（不重複建）。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id="dupe1",
            email="already@edms.local",
            pwd_hash=hash_password(_GOOD_PWD),
            user_name="已驗證",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="dupe1",
            created_date=now,
        )
    )
    token = await _seed_pending(db, email="already@edms.local")
    with pytest.raises(AppError) as exc:
        await VerifyService().verify(db, token=token)
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_001"


async def test_login_unverified_returns_specific_message(db):
    """未驗證帳號（僅 pending、不在 DP_USER）嘗試登入 → 401 DP_AUTH_010（非查無此帳號）。"""
    await _seed_pending(db, email="pendinglogin@edms.local")
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email="pendinglogin@edms.local", password=_GOOD_PWD)
    assert exc.value.status_code == 401 and exc.value.error_code == "DP_AUTH_010"


async def test_resend_replaces_token(db):
    """重寄 → 沿用 Email / 姓名，作廢舊 token、產新（單一列、token 換新）。"""
    old_token = await _seed_pending(db, email="resend@edms.local")
    await ResendVerificationService().resend(db, email="resend@edms.local")

    rows = (
        (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "resend@edms.local")))
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].token_hash != hash_token(old_token)


async def test_resend_unknown_email_noop(db):
    """重寄不存在的 pending Email → 靜默 no-op（防列舉），不建任何列。"""
    await ResendVerificationService().resend(db, email="nobody@edms.local")
    assert (
        await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == "nobody@edms.local"))
    ).scalar_one_or_none() is None


async def test_verify_grant_failure_propagates(db):
    """ET granter 拋例外 → verify **不吞例外**、往上傳播（交 get_db 對本請求交易 rollback，
    帳號 / 歷程 / 稽核 / 待驗證列皆不落地，同 register / login 既有回滾模式）。"""

    async def _boom(_db, _uid):
        raise RuntimeError("ET service down")

    module_provisioning_gate.register("ET", _boom)
    try:
        token = await _seed_pending(db, email="grantboom@edms.local")
        with pytest.raises(RuntimeError):
            await VerifyService().verify(db, token=token)
    finally:
        module_provisioning_gate.unregister("ET")


async def test_verify_grant_noop_when_unregistered(db):
    """ET 未掛 granter（無 et_stub）→ grant_default_role no-op、不擋驗證；帳號仍建立成功。"""
    token = await _seed_pending(db, email="noet@edms.local")
    await VerifyService().verify(db, token=token)
    user = (await db.execute(select(DpUser).where(DpUser.email == "noet@edms.local"))).scalar_one()
    assert user.status == "ACTIVE"


async def test_verify_consumed_token_reclick_rejected(db, et_stub):
    """成功消費後再點同一連結 → 400 DP_USER_003（待驗證列已刪、查無 token）。"""
    token = await _seed_pending(db, email="reclick@edms.local")
    await VerifyService().verify(db, token=token)
    with pytest.raises(AppError) as exc:
        await VerifyService().verify(db, token=token)
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_USER_003"


async def test_verify_email_endpoint(client, db, et_stub):
    """/api/verify-email 端點：有效 token → 200 + 建立 DP_USER。"""
    token = await _seed_pending(db, email="ep-verify@edms.local")
    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 200
    assert (
        await db.execute(select(DpUser).where(DpUser.email == "ep-verify@edms.local"))
    ).scalar_one_or_none() is not None


async def test_resend_endpoint_uniform_message(client):
    """/api/resend-verification 端點：無論 Email 是否有待驗證列，一律回相同訊息（防列舉）、200。"""
    r = await client.post("/api/resend-verification", json={"email": "whoever@edms.local"})
    assert r.status_code == 200 and "驗證信" in r.json()["message"]
