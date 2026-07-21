"""US3 忘記密碼（T028 申請 / T029 重設）整合測試：防列舉 / token 一次性時效 / 複雜度重複性 / 不改狀態。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.password_policy import hash_password, verify_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.models import DpPwdHistory, DpPwdReset
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"
_NEW_PWD = "Xyz98765!"


async def _make_user(db, *, user_id="fp", email="fp@edms.local", status="ACTIVE", locked_until=None):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email,
        pwd_hash=hash_password(_GOOD_PWD),
        user_name="忘密測試",
        status=status,
        login_fail_count=0,
        locked_until=locked_until,
        pwd_changed_date=now - timedelta(days=1),
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_token(db, *, user_id, plaintext="tok-plain-abc", minutes=30, used=False):
    now = utcnow()
    db.add(
        DpPwdReset(
            token_hash=hash_token(plaintext),
            user_id=user_id,
            token_type="PWD_RESET",
            expires_date=now + timedelta(minutes=minutes),
            used_date=now if used else None,
            created_user=user_id,
            created_date=now,
        )
    )
    await db.flush()
    return plaintext


class _NotifyStub:
    """記錄 send_email 呼叫的假發信服務（避免測試依賴真範本渲染）。"""

    def __init__(self):
        self.calls = []

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients, "template_code": template_code, "params": params})


# --- T028 申請 ---


async def test_forgot_existing_creates_token_and_sends(db):
    """存在帳號 → 產一次性 token（存 SHA-256）+ 經 SRVDP002 寄 PWD_RESET，params 含 reset_link。"""
    await _make_user(db, user_id="ex", email="ex@edms.local")
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="ex@edms.local")

    tokens = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "ex"))).scalars().all()
    assert len(tokens) == 1 and tokens[0].used_date is None and tokens[0].expires_date > utcnow()
    assert len(notify.calls) == 1
    call = notify.calls[0]
    assert call["recipients"] == ["ex@edms.local"] and call["template_code"] == "PWD_RESET"
    assert call["params"]["reset_link"].startswith("http") and "token=" in call["params"]["reset_link"]


async def test_forgot_nonexistent_silent(db):
    """不存在帳號 → 不產 token、不寄信（防列舉；端點仍回相同訊息）。"""
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="ghost@edms.local")
    assert notify.calls == []
    assert (await db.execute(select(DpPwdReset))).first() is None


async def test_forgot_invalidates_old_token(db):
    """重新申請 → 舊未使用 token 立即作廢、產新 token。"""
    await _make_user(db, user_id="re", email="re@edms.local")
    await _make_token(db, user_id="re", plaintext="old-token")
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="re@edms.local")

    rows = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "re"))).scalars().all()
    active = [r for r in rows if r.used_date is None]
    old = next(r for r in rows if r.token_hash == hash_token("old-token"))
    assert old.used_date is not None  # 舊 token 已作廢
    assert len(active) == 1 and active[0].token_hash != hash_token("old-token")  # 新 token


async def test_forgot_request_endpoint_uniform_message(client, db):
    """端點：不論帳號存在與否皆回 200 + 相同訊息（防列舉）。"""
    await _make_user(db, user_id="uni", email="uni@edms.local")
    r1 = await client.post("/api/forgot-password", json={"email": "uni@edms.local"})
    r2 = await client.post("/api/forgot-password", json={"email": "nobody@edms.local"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["message"] == r2.json()["message"]


# --- T029 重設 ---


async def test_reset_success(db):
    """有效 token + 合規新密碼 → 更新密碼 + 追加歷程 + 作廢 token + 稽核。"""
    await _make_user(db, user_id="rs", email="rs@edms.local")
    plaintext = await _make_token(db, user_id="rs")
    await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    user = (await db.execute(select(DpUser).where(DpUser.user_id == "rs"))).scalar_one()
    assert verify_password(_NEW_PWD, user.pwd_hash)
    hist = (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == "rs"))).scalars().all()
    assert any(verify_password(_NEW_PWD, h.pwd_hash) for h in hist)
    token = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "rs"))).scalar_one()
    assert token.used_date is not None  # token 作廢
    audit = (await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-FORGOT"))).scalars().all()
    assert audit and audit[-1].action_type == "UPDATE" and audit[-1].result == "SUCCESS"


async def test_reset_endpoint_success(client, db):
    """端點：有效 token + 合規新密碼 → 200 + 訊息，密碼實際更新（驗 router→schema→service 串接）。"""
    await _make_user(db, user_id="ep", email="ep@edms.local")
    plaintext = await _make_token(db, user_id="ep")
    r = await client.post(
        "/api/reset-password",
        json={"token": plaintext, "new_password": _NEW_PWD, "confirm_password": _NEW_PWD},
    )
    assert r.status_code == 200 and "密碼已更新" in r.json()["message"]
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ep"))).scalar_one()
    assert verify_password(_NEW_PWD, user.pwd_hash)


async def test_reset_expired_token(db):
    """token 逾時 → DP_PWD_005。"""
    await _make_user(db, user_id="ex2", email="ex2@edms.local")
    plaintext = await _make_token(db, user_id="ex2", minutes=-1)  # 已逾時
    with pytest.raises(AppError) as exc:
        await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_PWD_005"


async def test_reset_used_token(db):
    """token 已使用 → DP_PWD_005。"""
    await _make_user(db, user_id="us2", email="us2@edms.local")
    plaintext = await _make_token(db, user_id="us2", used=True)
    with pytest.raises(AppError) as exc:
        await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)
    assert exc.value.error_code == "DP_PWD_005"


async def test_reset_password_mismatch(db):
    """兩次不一致 → DP_USER_002。"""
    await _make_user(db, user_id="mm", email="mm3@edms.local")
    plaintext = await _make_token(db, user_id="mm")
    with pytest.raises(AppError) as exc:
        await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password="Diff9999!")
    assert exc.value.status_code == 422 and exc.value.error_code == "DP_USER_002"


async def test_reset_weak_password(db):
    """複雜度不足 → DP_PWD_00x。"""
    await _make_user(db, user_id="wk", email="wk@edms.local")
    plaintext = await _make_token(db, user_id="wk")
    with pytest.raises(AppError) as exc:
        await ResetPasswordService().reset(db, token=plaintext, new_password="abc", confirm_password="abc")
    assert exc.value.status_code == 422 and exc.value.error_code.startswith("DP_PWD_")


async def test_reset_reused_password(db):
    """新密碼與最近歷程相同 → DP_PWD_003。"""
    user = await _make_user(db, user_id="ru", email="ru@edms.local")
    # 歷程首筆為 _NEW_PWD 的雜湊
    db.add(
        DpPwdHistory(
            user_id=user.user_id,
            seq_no=1,
            pwd_hash=hash_password(_NEW_PWD),
            created_user=user.user_id,
            created_date=utcnow(),
        )
    )
    await db.flush()
    plaintext = await _make_token(db, user_id="ru")
    with pytest.raises(AppError) as exc:
        await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)
    assert exc.value.error_code == "DP_PWD_003"


async def test_reset_keeps_locked_and_status(db):
    """鎖定 / 停用帳號重設成功，但 LOCKED_UNTIL / STATUS 不變（FR-07）。"""
    locked_until = utcnow() + timedelta(minutes=30)
    await _make_user(db, user_id="lk", email="lk@edms.local", status="DISABLED", locked_until=locked_until)
    plaintext = await _make_token(db, user_id="lk")
    await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    user = (await db.execute(select(DpUser).where(DpUser.user_id == "lk"))).scalar_one()
    assert verify_password(_NEW_PWD, user.pwd_hash)  # 密碼已更新
    assert user.status == "DISABLED" and user.locked_until == locked_until  # 狀態不變
