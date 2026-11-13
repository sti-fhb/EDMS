"""US8 個人資料維護整合測試：姓名 / 密碼變更（驗舊 / 複雜度特權 12 / 重複性 / 清 MUST_CHANGE / 稽核）、
Email 延遲切換（唯一 / token 寄新信箱 / 舊仍有效 / 驗證切換 / 逾時作廢 / 停用擋下且不燒 token，#956）、
速率限制、公開密碼政策。"""

from datetime import datetime, timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, update

from app.core.auth import create_access_token, get_jwt_payload
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.password_policy import hash_password, verify_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user import profile_service as profile_service_module
from app.dp.user.email_change_service import EmailChangeService
from app.dp.user.models import DpPwdHistory, DpPwdReset
from app.dp.user.profile_service import ProfileService
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"
_NEW_PWD = "Xyz98765!"


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


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


async def test_change_password_invalidates_tokens_issued_before(db):
    """變更密碼後，變更前簽發的 token 立即失效；之後登入取得的仍正常（#941）。

    這條驗的是**因果鏈的終點**：`test_dp_auth_middleware` 那幾條手動設 `PWD_CHANGED_DATE`
    來驗閘門，證明不了「`change_password` 這個動作真的會推進該欄位」。少了本條，
    把 `update_password` 的 `pwd_changed_date` 拿掉也不會有任何測試變紅。

    ⚠️ 舊 token 的 `auth_time` 刻意取明確早於變更時點的值，**不可用當下簽發**：
    判定以整秒比較，同一秒內完成「簽發 → 改密碼」時 floor 後相等而不被拒。
    """
    await _make_user(db, user_id="cpinv", email="cpinv@edms.local")  # pwd_changed_date = 昨天
    old_token = create_access_token(sub="cpinv", ttl_minutes=15, auth_time=utcnow() - timedelta(minutes=5))

    # 前置：改密碼之前這張 token 是好的——少了它，下面的 401 可能根本與密碼變更無關
    payload = await get_jwt_payload(credentials=_creds(old_token), db=db)
    assert payload.sub == "cpinv"

    await ProfileService().change_password(
        db, user_id="cpinv", old_password=_GOOD_PWD, new_password=_NEW_PWD, confirm_password=_NEW_PWD
    )

    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(old_token), db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"

    # 變更後才簽發的 token 照常可用（否則使用者改完密碼就再也登不進來）
    new_payload = await get_jwt_payload(credentials=_creds(create_access_token(sub="cpinv", ttl_minutes=15)), db=db)
    assert new_payload.sub == "cpinv"


async def test_pwd_changed_date_taken_after_hashing(db, monkeypatch):
    """`PWD_CHANGED_DATE` 必須取在雜湊**之後**，不得沿用函式開頭的時間（#941）。

    它是「變更前簽發的 token 一律失效」的判定基準。函式開頭到寫入之間要跑 verify、
    三次 DB 往返與 `is_reused`（`HISTORY_COUNT` 上限 24 ⇒ 最長約 4.4 秒）——沿用開頭的值
    會讓這幾秒內以舊密碼登入取得的 token 在變更後仍然有效，直接抵銷本功能。

    🥇 判準取「雜湊被呼叫的時點」而非固定秒數：不依賴機器快慢、不需 sleep，而沿用開頭
    時間的實作必然早於它（中間隔著 verify 與多次查詢），因此一定紅。
    """
    await _make_user(db, user_id="cpts", email="cpts@edms.local")

    hash_called_at: list[datetime] = []
    real_hash = profile_service_module.hash_password_async

    async def spy_hash(password: str) -> str:
        hash_called_at.append(utcnow())
        return await real_hash(password)

    monkeypatch.setattr(profile_service_module, "hash_password_async", spy_hash)

    await ProfileService().change_password(
        db, user_id="cpts", old_password=_GOOD_PWD, new_password=_NEW_PWD, confirm_password=_NEW_PWD
    )

    assert hash_called_at, "前置：雜湊確實被呼叫過"
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "cpts"))).scalar_one()
    assert user.pwd_changed_date >= hash_called_at[0], (
        "PWD_CHANGED_DATE 早於雜湊開始，代表沿用了函式開頭的時間，變更期間的舊密碼登入會存活"
    )


async def test_change_password_wrong_old(db):
    """舊密碼錯 → 422 DP_PWD_006（PROFILE-001）。用 422 非 401：401 於前端代表 session 失效會誤登出。"""
    await _make_user(db, user_id="wo", email="wo@edms.local")
    with pytest.raises(AppError) as exc:
        await ProfileService().change_password(
            db, user_id="wo", old_password="WrongOld9", new_password=_NEW_PWD, confirm_password=_NEW_PWD
        )
    assert exc.value.status_code == 422 and exc.value.error_code == "DP_PWD_006"


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
            user_id=user.user_id,
            seq_no=1,
            pwd_hash=hash_password(_NEW_PWD),
            created_user=user.user_id,
            created_date=utcnow(),
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
    for _ in range(_pwd_change_limiter._max):
        _pwd_change_limiter.hit(key)
    r = await client.put(
        "/api/dp/user/me/password",
        json={"old_password": _GOOD_PWD, "new_password": _NEW_PWD, "confirm_password": _NEW_PWD},
        headers=_bearer("rl"),
    )
    assert r.status_code == 429


# --- GET /me（含 pending_email） ---


async def test_get_me_endpoint(client, db):
    """GET /me → 回姓名 / Email / pending_email。"""
    await _make_user(db, user_id="me", email="me@edms.local")
    r = await client.get("/api/dp/user/me", headers=_bearer("me"))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "me@edms.local" and body["user_name"] == "個資測試" and body["pending_email"] is None


async def _expire_email_change_tokens(db, user_id):
    """把該使用者所有 EMAIL_CHANGE token 的 EXPIRES_DATE 推到過去（模擬驗證連結逾期）。"""
    await db.execute(
        update(DpPwdReset)
        .where(DpPwdReset.user_id == user_id, DpPwdReset.token_type == "EMAIL_CHANGE")
        .values(expires_date=utcnow() - timedelta(minutes=1))
    )
    await db.flush()


async def test_get_me_pending_email_before_expiry(db):
    """驗證連結仍在效期內 → pending_email 照常回傳（「變更審核中」行為不變，#904）。"""
    await _make_user(db, user_id="pe1", email="pe1@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="pe1", new_email="pe1-new@edms.local")

    me = await ProfileService().get_me(db, user_id="pe1")
    assert me.email == "pe1@edms.local" and me.pending_email == "pe1-new@edms.local"


async def test_get_me_pending_email_after_expiry(client, db):
    """驗證連結逾期 → /me 回 pending_email=null（欄位殘值不再顯示「變更審核中」，#904）。"""
    await _make_user(db, user_id="pe2", email="pe2@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="pe2", new_email="pe2-new@edms.local")
    await _expire_email_change_tokens(db, "pe2")

    r = await client.get("/api/dp/user/me", headers=_bearer("pe2"))
    assert r.status_code == 200 and r.json()["pending_email"] is None


async def test_get_me_pending_email_after_token_invalidated(db):
    """token 已作廢（USED_DATE 有值）但 PENDING_EMAIL 殘值仍在 → 視為無待驗證（#904）。"""
    await _make_user(db, user_id="pe3", email="pe3@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="pe3", new_email="pe3-new@edms.local")
    await db.execute(update(DpPwdReset).where(DpPwdReset.user_id == "pe3").values(used_date=utcnow()))
    await db.flush()

    me = await ProfileService().get_me(db, user_id="pe3")
    assert me.pending_email is None


async def test_get_me_pending_email_mismatched_token_not_active(db):
    """token 仍有效但 NEW_EMAIL 與 PENDING_EMAIL 不符（資料修補 / 直接寫庫）→ 不算待驗證中（#904）。"""
    user = await _make_user(db, user_id="pe4", email="pe4@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="pe4", new_email="pe4-new@edms.local")
    user.pending_email = "other@edms.local"
    await db.flush()

    me = await ProfileService().get_me(db, user_id="pe4")
    assert me.pending_email is None


async def test_email_change_reapply_after_expiry_old_link_still_invalid(db):
    """逾期後再次申請：寄出新驗證信；舊（逾期）連結仍不可完成變更，新連結可（#904 AC2 / AC5）。"""
    await _make_user(db, user_id="ra", email="ra@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="ra", new_email="ra-old@edms.local")
    old_token = notify.calls[0]["params"]["verify_link"].split("token=")[1]
    await _expire_email_change_tokens(db, "ra")
    assert (await ProfileService().get_me(db, user_id="ra")).pending_email is None

    await EmailChangeService(notify=notify).request(db, user_id="ra", new_email="ra-new@edms.local")
    assert notify.calls[1]["recipients"] == ["ra-new@edms.local"]
    assert (await ProfileService().get_me(db, user_id="ra")).pending_email == "ra-new@edms.local"
    new_token = notify.calls[1]["params"]["verify_link"].split("token=")[1]

    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token=old_token)
    assert exc.value.error_code == "DP_PWD_005"
    await EmailChangeService().verify(db, token=new_token)
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ra"))).scalar_one()
    assert user.email == "ra-new@edms.local" and user.pending_email is None


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
    """他人已申請改為同一新信箱（連結仍在效期內）→ 申請即擋 DP_USER_007（延遲切換窗口，code review M2）。"""
    await _make_user(db, user_id="a1", email="a1@edms.local")
    await _make_user(db, user_id="b1", email="b1@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="b1", new_email="shared@edms.local")
    with pytest.raises(AppError) as exc:
        await EmailChangeService().request(db, user_id="a1", new_email="shared@edms.local")
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_USER_007"


async def test_email_change_allows_others_expired_pending(db):
    """他人申請的新信箱連結已逾期（PENDING_EMAIL 殘值仍在）→ 不再占用，可被其他帳號申請（#904）。"""
    await _make_user(db, user_id="a2", email="a2@edms.local")
    await _make_user(db, user_id="b2", email="b2@edms.local")
    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="b2", new_email="freed@edms.local")
    await _expire_email_change_tokens(db, "b2")

    await EmailChangeService(notify=_NotifyStub()).request(db, user_id="a2", new_email="freed@edms.local")
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "a2"))).scalar_one()
    assert user.pending_email == "freed@edms.local"


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
            token_hash=hash_token("expired-tok"),
            user_id=user.user_id,
            token_type="EMAIL_CHANGE",
            new_email="never@edms.local",
            expires_date=now - timedelta(minutes=1),
            created_user=user.user_id,
            created_date=now,
        )
    )
    await db.flush()
    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token="expired-tok")
    assert exc.value.error_code == "DP_PWD_005"
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "ev"))).scalar_one()
    assert user.email == "keep@edms.local"


async def test_email_change_verify_rejects_token_not_matching_pending(db):
    """token 有效但 NEW_EMAIL 已非目前 PENDING_EMAIL（並發重複申請殘留）→ DP_PWD_005，EMAIL 不變。

    「變更審核中」只認 NEW_EMAIL 與 PENDING_EMAIL 相同之 token（#904），完成變更須採同一判定，
    否則畫面顯示審核中 Y、點 X 的連結卻切成 X。
    """
    user = await _make_user(db, user_id="mm", email="mm@edms.local")
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id="mm", new_email="mm-x@edms.local")
    token_plain = notify.calls[0]["params"]["verify_link"].split("token=")[1]
    user.pending_email = "mm-y@edms.local"  # 模擬並發的另一筆申請最後寫入 PENDING_EMAIL
    await db.flush()

    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token=token_plain)
    assert exc.value.error_code == "DP_PWD_005"
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "mm"))).scalar_one()
    assert user.email == "mm@edms.local"


async def test_email_change_endpoint_normalizes_email(client, db):
    """端點：新 Email 大小寫正規化（#35）→ 存入 PENDING_EMAIL 為 strip+lower，與登入查詢一致。"""
    await _make_user(db, user_id="nz", email="nz@edms.local")
    r = await client.put("/api/dp/user/me/email", json={"new_email": "  New.Case@Edms.Local  "}, headers=_bearer("nz"))
    assert r.status_code == 202
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "nz"))).scalar_one()
    assert user.pending_email == "new.case@edms.local"


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


async def test_email_change_cooldown(client, db):
    """寄驗證信有冷卻（#74）：成功寄一次後，冷卻內再寄 → 429（防狂發）。"""
    await _make_user(db, user_id="cd", email="cd@edms.local")
    r1 = await client.put("/api/dp/user/me/email", json={"new_email": "cd-new@edms.local"}, headers=_bearer("cd"))
    assert r1.status_code == 202
    r2 = await client.put("/api/dp/user/me/email", json={"new_email": "cd-new2@edms.local"}, headers=_bearer("cd"))
    assert r2.status_code == 429


# --- 停用帳號不得完成 Email 變更（#956） ---


async def _email_change_token(db, *, user_id: str, new_email: str) -> str:
    """申請一次 Email 變更，回傳驗證信連結中的明文 token。"""
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id=user_id, new_email=new_email)
    return notify.calls[0]["params"]["verify_link"].split("token=")[1]


async def test_email_change_verify_停用帳號被擋且三個欄位都不動(db):
    """停用後點連結 → 400 `DP_PWD_007`；EMAIL / PENDING_EMAIL / USED_DATE 三者皆不變（#956 AC 1、3）。

    ⚠️ **USED_DATE 要一起驗**：擋下、但把 token 一併燒掉的寫法同樣能讓前兩個斷言通過，
    而那正是 SA 裁示 Q2 否決的行為（帳號恢復後使用者得重新申請）。少了這條斷言，
    「擋下前先消費」與「擋下時不消費」兩種實作都會全綠。
    """
    user = await _make_user(db, user_id="dz", email="dz@edms.local")
    token_plain = await _email_change_token(db, user_id="dz", new_email="dz-new@edms.local")
    user.status = "DISABLED"
    await db.flush()

    with pytest.raises(AppError) as exc:
        await EmailChangeService().verify(db, token=token_plain)
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_PWD_007"
    assert exc.value.detail == "帳號已停用，請洽管理者"

    user = (await db.execute(select(DpUser).where(DpUser.user_id == "dz"))).scalar_one()
    assert user.email == "dz@edms.local", "EMAIL 不得切換"
    assert user.pending_email == "dz-new@edms.local", "PENDING_EMAIL 不得清空"
    row = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "dz"))).scalar_one()
    assert row.used_date is None, "擋下時不得消費 token（SA 裁示 Q2）"


async def test_email_change_verify_重新啟用後同一連結仍可用(db):
    """停用擋下 → 重新啟用 → 同一連結仍在 TTL 內 → 變更照常完成（#956 AC 2）。

    與 `PWD_RESET` 行為一致：#958 裁示 2 判定「管理者按下啟用」本身就是「已判定該帳號沒問題」。
    """
    user = await _make_user(db, user_id="re", email="re@edms.local")
    token_plain = await _email_change_token(db, user_id="re", new_email="re-new@edms.local")
    user.status = "DISABLED"
    await db.flush()
    with pytest.raises(AppError):
        await EmailChangeService().verify(db, token=token_plain)

    # ⚠️ 擋下路徑內含 commit，實體可能已過期 → 重查再改，不要沿用上面的 user
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "re"))).scalar_one()
    user.status = "ACTIVE"
    await db.flush()

    await EmailChangeService().verify(db, token=token_plain)
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "re"))).scalar_one()
    assert user.email == "re-new@edms.local" and user.pending_email is None


async def test_email_change_verify_鎖定中不被擋(db):
    """正向錨點：鎖定中（`STATUS` 仍 `ACTIVE`）照常完成——鎖定是暫時的，非本案標的（#956 AC 5）。

    ⚠️ 判定若誤用 `is_account_usable()`（把鎖定也算成不可用）**不會有任何東西報錯**，
    只有這條會紅。#953 / #958 都在這個分界上踩過。
    """
    user = await _make_user(db, user_id="lk", email="lk@edms.local")
    token_plain = await _email_change_token(db, user_id="lk", new_email="lk-new@edms.local")
    user.locked_until = utcnow() + timedelta(minutes=15)
    await db.flush()

    await EmailChangeService().verify(db, token=token_plain)
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "lk"))).scalar_one()
    assert user.email == "lk-new@edms.local"


async def test_email_change_verify_停用帳號的稽核確實落地(client, db):
    """🔴 **刻意走端點**驗稽核落地（#956 AC 6）。

    `get_db` 對 `AppError` 會 rollback，稽核列會被一併抹除——結果是「程式有寫、DP05 查不到」。
    這個缺陷是靜默的：測試若在 service 層直接呼叫、或只驗 `log_action` 有被呼叫，兩種寫法都全綠。
    範式與理由同 `forgot_service._audit_reset_fail`（#958）。
    """
    user = await _make_user(db, user_id="az", email="az@edms.local")
    token_plain = await _email_change_token(db, user_id="az", new_email="az-new@edms.local")
    user.status = "DISABLED"
    await db.flush()

    r = await client.post("/api/verify-email-change", json={"token": token_plain})
    assert r.status_code == 400 and r.json()["error_code"] == "DP_PWD_007"

    rows = (
        (
            await db.execute(
                select(DpAuditLog)
                .where(DpAuditLog.func_name == "DP-PROFILE", DpAuditLog.result == "FAIL")
                .order_by(DpAuditLog.log_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"停用分支的失敗稽核未落地，實得 {len(rows)} 筆"
    assert rows[0].action_type == "UPDATE"
    assert rows[0].created_user == "az" and rows[0].target_id == "az"
    # ⛔ 新 Email 是申請時自選的字串、屬個資；#958 CR HIGH 正是把 Email 寫進 TARGET_ID(100) 撐爆長度
    assert "az-new@edms.local" not in f"{rows[0].description} {rows[0].target_id}"


async def test_switch_email_停用帳號一列都改不到(db):
    """寫入端自帶 `account_not_disabled_clause()`：帳號已停用時回 `False`、`EMAIL` 不變（#956 安審 MEDIUM-1）。

    ⚠️ 這條守的是**預檢與寫入之間的競態**，與預檢本身是兩回事。管理者的停用交易若先取得該列
    行鎖，本 UPDATE 會**等鎖而非失敗**；等鎖結束後 READ COMMITTED 會重新評估 WHERE——若 WHERE
    只有主鍵（改序前的 ORM 賦值就是如此），條件自然仍成立，Email 照樣被改掉。把
    `account_not_disabled_clause()` 從 where 拿掉，只有這條會紅。
    """
    await _make_user(db, user_id="rc", email="rc@edms.local")
    await db.execute(update(DpUser).where(DpUser.user_id == "rc").values(status="DISABLED"))

    switched = await AuthRepository().switch_email(
        db, user_id="rc", new_email="rc-new@edms.local", operator_id="rc", now=utcnow()
    )
    assert switched is False
    # 取純欄位而非實體：避開 identity map 回傳記憶體中舊值的可能
    email = (await db.execute(select(DpUser.email).where(DpUser.user_id == "rc"))).scalar_one()
    assert email == "rc@edms.local"


# --- 公開密碼政策（併 #77） ---


async def test_password_policy_endpoint_public(client):
    """GET /password-policy 免 JWT → 回非機密門檻數值。"""
    r = await client.get("/api/password-policy")
    assert r.status_code == 200
    body = r.json()
    for k in ("min_len", "admin_min_len", "char_types", "history_count", "expiry_days"):
        assert isinstance(body[k], int)
    assert body["admin_min_len"] >= body["min_len"]
