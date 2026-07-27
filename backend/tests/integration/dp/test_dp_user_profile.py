"""US8 個人資料維護整合測試：姓名 / 密碼變更（驗舊 / 複雜度特權 12 / 重複性 / 清 MUST_CHANGE / 稽核）、
Email 延遲切換（唯一 / token 寄新信箱 / 舊仍有效 / 驗證切換 / 逾時作廢）、速率限制、公開密碼政策。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.password_policy import hash_password, verify_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.email_change_service import EmailChangeService
from app.dp.user.models import DpPwdHistory, DpPwdReset
from app.dp.user.profile_service import ProfileService
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"
_NEW_PWD = "Xyz98765!"


async def _make_user(db, *, user_id="pf", email="pf@edms.local", must_change=False, pwd=_GOOD_PWD):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email,
        pwd_hash=hash_password(pwd),
        user_name="個資測試",
        status="ACTIVE",
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=1),
        must_change_pwd=must_change,
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


def _bearer(user_id):
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


class _NotifyStub:
    """記錄 send_email 呼叫的假發信服務（避免依賴真範本渲染）。"""

    def __init__(self):
        self.calls = []

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients, "template_code": template_code, "params": params})


# --- 姓名變更（AC1） ---


async def test_update_name_persists_and_audits(db):
    """姓名變更 → 直接更新 DP_USER + 稽核（含前後值）。"""
    await _make_user(db, user_id="nm", email="nm@edms.local")
    await ProfileService().update_name(db, user_id="nm", user_name="新名字")

    user = (await db.execute(select(DpUser).where(DpUser.user_id == "nm"))).scalar_one()
    assert user.user_name == "新名字"
    audit = (await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-PROFILE"))).scalars().all()
    assert audit and audit[-1].action_type == "UPDATE" and audit[-1].result == "SUCCESS"


async def test_update_name_endpoint(client, db):
    """端點 PUT /me → 204 + 姓名實際更新（驗 router→schema→service 串接）。"""
    await _make_user(db, user_id="ne", email="ne@edms.local")
    r = await client.put("/api/dp/user/me", json={"user_name": "端點改名"}, headers=_bearer("ne"))
    assert r.status_code == 204
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ne"))).scalar_one()
    assert user.user_name == "端點改名"


# --- 密碼變更（AC5 / AC6 / AC7） ---


async def test_change_password_success(db):
    """驗舊 + 合規新密碼 → 更新雜湊 + 追加歷程 + 清 MUST_CHANGE + 稽核。"""
    await _make_user(db, user_id="cp", email="cp@edms.local", must_change=True)
    await ProfileService().change_password(
        db, user_id="cp", old_password=_GOOD_PWD, new_password=_NEW_PWD, confirm_password=_NEW_PWD
    )
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "cp"))).scalar_one()
    assert verify_password(_NEW_PWD, user.pwd_hash)
    assert user.must_change_pwd is False  # 強制變更旗標已清（AC / FR-08 收尾）
    hist = (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == "cp"))).scalars().all()
    assert any(verify_password(_NEW_PWD, h.pwd_hash) for h in hist)


async def test_change_password_wrong_old(db):
    """舊密碼錯 → DP_AUTH_008（PROFILE-001）。"""
    await _make_user(db, user_id="wo", email="wo@edms.local")
    with pytest.raises(AppError) as exc:
        await ProfileService().change_password(
            db, user_id="wo", old_password="WrongOld9", new_password=_NEW_PWD, confirm_password=_NEW_PWD
        )
    assert exc.value.status_code == 401 and exc.value.error_code == "DP_AUTH_008"


async def test_change_password_mismatch(db):
    """兩次不一致 → DP_USER_002（PROFILE-002）。"""
    await _make_user(db, user_id="ms", email="ms@edms.local")
    with pytest.raises(AppError) as exc:
        await ProfileService().change_password(
            db, user_id="ms", old_password=_GOOD_PWD, new_password=_NEW_PWD, confirm_password="Diff9999!"
        )
    assert exc.value.error_code == "DP_USER_002"


async def test_change_password_weak(db):
    """複雜度 / 長度不足 → DP_PWD_00x（PROFILE-003）。"""
    await _make_user(db, user_id="wk", email="wk@edms.local")
    with pytest.raises(AppError) as exc:
        await ProfileService().change_password(
            db, user_id="wk", old_password=_GOOD_PWD, new_password="abc", confirm_password="abc"
        )
    assert exc.value.error_code.startswith("DP_PWD_")


async def test_change_password_reused(db):
    """新密碼與最近歷程相同 → DP_PWD_003（PROFILE-004）。"""
    user = await _make_user(db, user_id="ru", email="ru@edms.local")
    db.add(
        DpPwdHistory(
            user_id=user.user_id, seq_no=1, pwd_hash=hash_password(_NEW_PWD),
            created_user=user.user_id, created_date=utcnow(),
        )
    )
    await db.flush()
    with pytest.raises(AppError) as exc:
        await ProfileService().change_password(
            db, user_id="ru", old_password=_GOOD_PWD, new_password=_NEW_PWD, confirm_password=_NEW_PWD
        )
    assert exc.value.error_code == "DP_PWD_003"


async def test_change_password_privileged_min_len(db):
    """特權帳號（ET 管理者）→ 12 字元門檻（8 字元合規密碼被拒 DP_PWD_001）。"""
    await _make_user(db, user_id="ad", email="ad@edms.local")

    async def _et_admin(_db, _uid):
        return True

    module_admin_gate.register("ET", _et_admin)
    try:
        # 8 字元、3 種字元組合 → 對特權門檻（12）不足
        with pytest.raises(AppError) as exc:
            await ProfileService().change_password(
                db, user_id="ad", old_password=_GOOD_PWD, new_password="Abcd123!", confirm_password="Abcd123!"
            )
        assert exc.value.error_code == "DP_PWD_001"
        # 12 字元 → 通過
        await ProfileService().change_password(
            db, user_id="ad", old_password=_GOOD_PWD, new_password="Abcd1234efg!", confirm_password="Abcd1234efg!"
        )
    finally:
        module_admin_gate.unregister("ET")
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ad"))).scalar_one()
    assert verify_password("Abcd1234efg!", user.pwd_hash)


async def test_change_password_endpoint_rate_limited(client, db):
    """密碼變更端點掛速率限制（FR-07 / AC8）：IP 桶灌滿後再請求 → 429（於 rate_limit_by_ip 閘擋下）。

    以預先灌滿 IP 桶驗「端點確實掛限流」——429 由限流 dependency 於 handler 前拋出，
    不依賴 user 存在（亦避開「錯誤請求觸發 override rollback 清掉 fixture 資料」的測試互動）。
    """
    from app.dp.user.router import _pwd_change_limiter

    await _make_user(db, user_id="rl", email="rl@edms.local")  # operator 依賴先於限流解析，需存在 user
    key = "pwd-change:ip:127.0.0.1"  # ASGITransport 測試恆為 127.0.0.1（見 rate_limit_by_ip）
    _pwd_change_limiter._hits.pop(key, None)
    try:
        for _ in range(_pwd_change_limiter._max):
            _pwd_change_limiter.hit(key)
        r = await client.put(
            "/api/dp/user/me/password",
            json={"old_password": _GOOD_PWD, "new_password": _NEW_PWD, "confirm_password": _NEW_PWD},
            headers=_bearer("rl"),
        )
        assert r.status_code == 429
    finally:
        _pwd_change_limiter._hits.pop(key, None)


# --- GET /me（含 pending_email） ---


async def test_get_me_endpoint(client, db):
    """GET /me → 回姓名 / Email / pending_email。"""
    await _make_user(db, user_id="me", email="me@edms.local")
    r = await client.get("/api/dp/user/me", headers=_bearer("me"))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "me@edms.local" and body["user_name"] == "個資測試" and body["pending_email"] is None


# --- Email 變更延遲切換（AC2 / AC3 / AC4） ---


async def test_email_change_request_creates_token_and_pending(db):
    """申請 → 產 EMAIL_CHANGE token（帶 NEW_EMAIL）+ 設 PENDING_EMAIL + 寄新信箱；EMAIL 未變（舊仍可登入）。"""
    await _make_user(db, user_id="ec", email="old@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="ec", new_email="new@edms.local")

    token = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "ec"))).scalar_one()
    assert token.token_type == "EMAIL_CHANGE" and token.new_email == "new@edms.local" and token.used_date is None
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ec"))).scalar_one()
    assert user.email == "old@edms.local" and user.pending_email == "new@edms.local"  # 延遲生效
    assert notify.calls[0]["recipients"] == ["new@edms.local"]
    assert notify.calls[0]["template_code"] == "EMAIL_CHANGE_VERIFY"
    assert "verify-email-change?token=" in notify.calls[0]["params"]["verify_link"]


async def test_email_change_duplicate_rejected(db):
    """新 Email 已被他人使用 → DP_USER_007（PROFILE-006）。"""
    await _make_user(db, user_id="d1", email="d1@edms.local")
    await _make_user(db, user_id="d2", email="taken@edms.local")
    with pytest.raises(AppError) as exc:
        await EmailChangeService().request(db, user_id="d1", new_email="taken@edms.local")
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_007"


async def test_email_change_rejects_others_pending(db):
    """他人已申請改為同一新信箱（尚未驗證）→ 申請即擋 DP_USER_007（延遲切換窗口，code review M2）。"""
    await _make_user(db, user_id="a1", email="a1@edms.local")
    other = await _make_user(db, user_id="b1", email="b1@edms.local")
    other.pending_email = "shared@edms.local"  # b1 已申請改為 shared@，尚未驗證
    await db.flush()
    with pytest.raises(AppError) as exc:
        await EmailChangeService().request(db, user_id="a1", new_email="shared@edms.local")
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_007"


async def test_email_change_verify_conflict_returns_409(db):
    """TTL 窗口內他人搶用同一 Email → verify 切換撞 UNIQUE，攔 IntegrityError 轉 409（非 500，code review M2）。"""
    await _make_user(db, user_id="cf", email="cf@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="cf", new_email="race@edms.local")
    token_plain = notify.calls[0]["params"]["verify_link"].split("token=")[1]
    await _make_user(db, user_id="other", email="race@edms.local")  # 窗口內他人搶註冊
    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token=token_plain)
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_007"


async def test_email_change_verify_switches(db):
    """點連結未逾時 → 切 EMAIL、清 PENDING、作廢 token、稽核。"""
    await _make_user(db, user_id="vf", email="old2@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="vf", new_email="new2@edms.local")
    token_plain = notify.calls[0]["params"]["verify_link"].split("token=")[1]

    await EmailChangeService().verify(db, token=token_plain)
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "vf"))).scalar_one()
    assert user.email == "new2@edms.local" and user.pending_email is None
    row = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "vf"))).scalar_one()
    assert row.used_date is not None


async def test_email_change_verify_expired(db):
    """token 逾時 → DP_PWD_005，EMAIL 維持原值。"""
    user = await _make_user(db, user_id="ev", email="keep@edms.local")
    now = utcnow()
    db.add(
        DpPwdReset(
            token_hash=hash_token("expired-tok"), user_id=user.user_id, token_type="EMAIL_CHANGE",
            new_email="never@edms.local", expires_date=now - timedelta(minutes=1),
            created_user=user.user_id, created_date=now,
        )
    )
    await db.flush()
    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token="expired-tok")
    assert exc.value.error_code == "DP_PWD_005"
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ev"))).scalar_one()
    assert user.email == "keep@edms.local"


async def test_verify_email_change_endpoint(client, db):
    """端點：公開落點，有效 token → 200 + EMAIL 切換。"""
    await _make_user(db, user_id="ve", email="oe@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="ve", new_email="ne2@edms.local")
    token_plain = notify.calls[0]["params"]["verify_link"].split("token=")[1]
    r = await client.post("/api/verify-email-change", json={"token": token_plain})
    assert r.status_code == 200
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ve"))).scalar_one()
    assert user.email == "ne2@edms.local"


# --- 公開密碼政策（併 #77） ---


async def test_password_policy_endpoint_public(client):
    """GET /password-policy 免 JWT → 回非機密門檻數值。"""
    r = await client.get("/api/password-policy")
    assert r.status_code == 200
    body = r.json()
    for k in ("min_len", "admin_min_len", "char_types", "history_count", "expiry_days"):
        assert isinstance(body[k], int)
    assert body["admin_min_len"] >= body["min_len"]
