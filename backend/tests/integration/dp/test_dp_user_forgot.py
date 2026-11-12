"""US3 忘記密碼（T028 申請 / T029 重設）整合測試：防列舉 / token 一次性時效 / 複雜度重複性 / 不改狀態。"""

from datetime import timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from app.core.auth import create_access_token, get_jwt_payload
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


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


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
    """端點：正常 / 不存在 / **停用**三者皆回 200 + **逐字相同**的完整 body（防列舉，#953）。

    🔴 比的是整個 `r.json()` 而不是 `["message"]`：#953 讓停用帳號走與「不存在」相同的早退路徑，
    若日後有人為了可觀測性在回應裡加個欄位（如 `sent: true`），只比 message 的版本會全綠，
    而那個欄位正好把三者切成兩組——防列舉就退化了。
    """
    await _make_user(db, user_id="uni", email="uni@edms.local")
    await _make_user(db, user_id="unid", email="unid@edms.local", status="DISABLED")
    r_active = await client.post("/api/forgot-password", json={"email": "uni@edms.local"})
    r_unknown = await client.post("/api/forgot-password", json={"email": "nobody@edms.local"})
    r_disabled = await client.post("/api/forgot-password", json={"email": "unid@edms.local"})

    codes = {r_active.status_code, r_unknown.status_code, r_disabled.status_code}
    assert codes == {200}, f"三者 HTTP 狀態不一致：{codes}"
    assert r_disabled.json() == r_active.json() == r_unknown.json(), (
        f"停用={r_disabled.json()} 正常={r_active.json()} 不存在={r_unknown.json()}——可據此區分帳號狀態"
    )


async def test_forgot_disabled_creates_no_token_and_no_mail(db):
    """停用帳號申請 → 不產 token、不寄信（#953）。

    ⚠️ 與 `test_forgot_nonexistent_silent` 不重複：那條驗的是「查無此人」，本條驗的是
    **查得到但不該服務**。兩者走同一條早退，但只有本條會因為「漏判 STATUS」而紅。
    """
    await _make_user(db, user_id="dis", email="dis@edms.local", status="DISABLED")
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="dis@edms.local")

    assert notify.calls == [], "停用帳號不應寄出重設信"
    rows = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "dis"))).scalars().all()
    assert rows == [], "停用帳號不應產生重設 token"


async def test_forgot_disabled_does_not_invalidate_existing_token(db):
    """停用帳號申請 → **連舊 token 都不動**（#953）。

    🔴 正向錨點的反面用途：若實作把狀態檢查放在 `invalidate_active_reset_tokens` **之後**，
    上面兩條仍會全綠（沒產新 token、沒寄信），但停用帳號的申請會變成一個「可以作廢別人
    既有連結」的無認證操作。本條把早退的**位置**釘住，不只釘住結果。
    """
    await _make_user(db, user_id="dis2", email="dis2@edms.local", status="DISABLED")
    await _make_token(db, user_id="dis2", plaintext="still-valid")
    await ForgotPasswordService(notify=_NotifyStub()).request(db, email="dis2@edms.local")

    row = (await db.execute(select(DpPwdReset).where(DpPwdReset.token_hash == hash_token("still-valid")))).scalar_one()
    assert row.used_date is None, "停用帳號的申請不應作廢既有 token"


# --- T028 申請端稽核（#958）---


async def _forgot_audits(db):
    """取本次測試寫入的 DP-FORGOT 稽核列（依寫入序）。"""
    rows = await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-FORGOT").order_by(DpAuditLog.log_id))
    return rows.scalars().all()


async def test_forgot_audit_正常帳號記已寄出(db):
    """申請成功 → 一筆 `CREATE` / `SUCCESS`，操作者與對象皆為該帳號（#958 AC 1）。"""
    await _make_user(db, user_id="au1", email="au1@edms.local")
    await ForgotPasswordService(notify=_NotifyStub()).request(db, email="au1@edms.local")

    rows = await _forgot_audits(db)
    assert len(rows) == 1, f"應恰好一筆，實得 {len(rows)}"
    row = rows[0]
    assert (row.action_type, row.result) == ("CREATE", "SUCCESS")
    assert row.created_user == "au1" and row.target_id == "au1"


async def test_forgot_audit_經端點呼叫時記得到來源IP(client, db):
    """稽核的 `SOURCE_IP` 必須落地（#958）。

    🔴 本條**刻意走端點**而非 service：`get_client_ip()` 取的是請求情境，service 層直接呼叫時
    恆為 `None`——把這條斷言寫在 service 層測試裡會永遠紅，寫成 `is None` 則是釘住了錯的契約。

    ⚠️ 「稽核漏記來源 IP」在本專案是有前例的真缺陷（#790 即為此開立），所以這條不是裝飾：
    少了 IP，事故調查只剩「有人試過」的計數，問不出是誰。
    """
    await _make_user(db, user_id="aip", email="aip@edms.local")
    r = await client.post("/api/forgot-password", json={"email": "aip@edms.local"})
    assert r.status_code == 200, r.text

    rows = await _forgot_audits(db)
    assert len(rows) == 1
    assert rows[0].source_ip, f"稽核未記來源 IP：{rows[0].source_ip!r}"


async def test_forgot_audit_帳號不存在記未寄出且Email已遮罩(db):
    """帳號不存在 → `FAIL`；操作者為 SYSTEM、Email **遮罩後**才入稽核（#958 AC 1/3）。

    🔴 比的是「不含完整 Email」而非只看有沒有 `*`：`CREATED_USER` 是 VARCHAR(20)、本來就塞不下
    Email，所以漏遮罩時 Email 會落在 `target_id` / `description`。稽核表不可刪，寫進去就拿不掉。
    """
    await ForgotPasswordService(notify=_NotifyStub()).request(db, email="ghost@edms.local")

    rows = await _forgot_audits(db)
    assert len(rows) == 1
    row = rows[0]
    assert (row.action_type, row.result) == ("CREATE", "FAIL")
    assert row.created_user == "SYSTEM"
    blob = f"{row.target_id or ''} {row.description or ''}"
    assert "ghost@edms.local" not in blob, f"完整 Email 寫進稽核：{blob}"
    assert "g" in blob and "*" in blob, f"遮罩後應仍可辨識來源，實得：{blob}"


async def test_forgot_audit_停用帳號記未寄出(db):
    """停用帳號 → `FAIL`，且**仍不產 token、不寄信**（#953 行為不得退化；#958 AC 1）。"""
    await _make_user(db, user_id="au3", email="au3@edms.local", status="DISABLED")
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="au3@edms.local")

    rows = await _forgot_audits(db)
    assert len(rows) == 1
    assert (rows[0].action_type, rows[0].result) == ("CREATE", "FAIL")
    assert rows[0].created_user == "au3"
    assert notify.calls == [] and (await db.execute(select(DpPwdReset))).first() is None


async def test_forgot_audit_鎖定中帳號照常寄出(db):
    """鎖定中（STATUS 仍 ACTIVE）→ 照常寄信且稽核記 `SUCCESS`（#958 AC 4）。

    ⚠️ 與停用那條成對：把判定寫成 `is_account_usable()`（含鎖定）時，本條會紅而停用那條仍綠。
    """
    await _make_user(
        db, user_id="au4", email="au4@edms.local", status="ACTIVE", locked_until=utcnow() + timedelta(minutes=30)
    )
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="au4@edms.local")

    rows = await _forgot_audits(db)
    assert len(rows) == 1 and rows[0].result == "SUCCESS"
    assert len(notify.calls) == 1, "鎖定中仍須收得到重設信"


async def test_forgot_audit_三種情況的稽核互相可分辨(db):
    """🔴 AC 1 的核心：三種情況**從稽核內容分得出來**。

    前四條各自驗一種情況，但「三者可分辨」是它們**合起來**才成立的性質——
    若三種都寫成同一句 description，前四條仍會全綠。本條把三者放在同一次測試裡比對。
    """
    await _make_user(db, user_id="d1", email="d1@edms.local")
    await _make_user(db, user_id="d2", email="d2@edms.local", status="DISABLED")
    svc = ForgotPasswordService(notify=_NotifyStub())
    await svc.request(db, email="d1@edms.local")
    await svc.request(db, email="nobody@edms.local")
    await svc.request(db, email="d2@edms.local")

    rows = await _forgot_audits(db)
    assert len(rows) == 3
    descs = [r.description for r in rows]
    assert len(set(descs)) == 3, f"三種情況的 description 必須互異，實得：{descs}"
    assert [r.result for r in rows] == ["SUCCESS", "FAIL", "FAIL"]


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


async def test_reset_invalidates_tokens_issued_before(db):
    """忘記密碼重設後，重設前簽發的 token 立即失效（#941）。

    帳號遭他人登入時，主人走忘記密碼也能踢掉對方——與自行變更密碼同一條閘，
    但走的是另一支 service，故兩邊都要驗（`reset` 與 `change_password` 各自呼叫
    `update_password`，其中一邊漏掉就只有一半生效）。

    ⚠️ 舊 token 的 `auth_time` 刻意取明確早於重設時點的值，不可用當下簽發：
    判定以整秒比較，同一秒內完成會 floor 後相等而不被拒。
    """
    await _make_user(db, user_id="rsinv", email="rsinv@edms.local")  # pwd_changed_date = 昨天
    old_token = create_access_token(sub="rsinv", ttl_minutes=15, auth_time=utcnow() - timedelta(minutes=5))

    # 前置：重設之前這張 token 是好的
    assert (await get_jwt_payload(credentials=_creds(old_token), db=db)).sub == "rsinv"

    plaintext = await _make_token(db, user_id="rsinv")
    await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(old_token), db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"

    # 重設後才簽發的 token 照常可用
    fresh = create_access_token(sub="rsinv", ttl_minutes=15)
    assert (await get_jwt_payload(credentials=_creds(fresh), db=db)).sub == "rsinv"


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


async def test_reset_keeps_locked(db):
    """**鎖定中**（但 STATUS=ACTIVE）的帳號重設成功，且 LOCKED_UNTIL 不變（FR-DP-US3-07）。

    🔴 #953 之前本條叫 `test_reset_keeps_locked_and_status`，用的是一個**同時**鎖定又停用的
    帳號，等於拿同一個帳號驗兩個維度。#953 把「停用」改成擋下，那個寫法就不再成立——但
    FR-07 的**鎖定**半邊完全沒變，所以改用鎖定中的 ACTIVE 帳號續守，不是刪掉它。

    ⛔ 不要為了「省一個帳號」把 status 改回 DISABLED：鎖定是暫時的、規格的用意就是讓使用者
    自己重設後等待解鎖；停用是管理者的決定。兩者混在一條測試裡，`is_account_usable()`（把兩個
    維度綁在一起的那支述詞）被誤用時不會有任何東西變紅。
    """
    locked_until = utcnow() + timedelta(minutes=30)
    await _make_user(db, user_id="lk", email="lk@edms.local", status="ACTIVE", locked_until=locked_until)
    plaintext = await _make_token(db, user_id="lk")
    await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    user = (await db.execute(select(DpUser).where(DpUser.user_id == "lk"))).scalar_one()
    assert verify_password(_NEW_PWD, user.pwd_hash)  # 密碼已更新
    assert user.locked_until == locked_until, "重設不得解除鎖定（FR-DP-US3-07）"
    assert user.status == "ACTIVE"


async def test_forgot_request_allowed_while_locked(db):
    """鎖定中的 ACTIVE 帳號**照常**可申請重設信（#953 AC 6）。

    ⚠️ 這條與上一條成對：少了它，把 `request` 的判定寫成 `is_account_usable()`（含鎖定）
    一樣會讓「停用被擋」的測試全綠，而鎖定中的使用者從此收不到重設信——那正是規格要給他的
    自助出路。
    """
    await _make_user(
        db, user_id="lkq", email="lkq@edms.local", status="ACTIVE", locked_until=utcnow() + timedelta(minutes=30)
    )
    notify = _NotifyStub()
    await ForgotPasswordService(notify=notify).request(db, email="lkq@edms.local")

    assert len(notify.calls) == 1, "鎖定中的帳號仍須收得到重設信"
    rows = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "lkq"))).scalars().all()
    assert len(rows) == 1


async def test_reset_blocked_for_disabled_identical_to_invalid_token(db):
    """**停用前**已寄出、尚未過期的連結，於重設時一律失效，且回應與 token 失效**逐字相同**（#953 AC 3）。

    這是本案真正要堵的那條路：只擋申請端的話，停用當下還在使用者（或讀得到信的人）手上的
    連結仍然有效，TTL 預設 30 分鐘。

    🔴 比到 `detail` 而不只是 `(status_code, error_code)`：`forgot_service` 的 docstring 宣稱
    兩者「逐字相同」，而只比前兩項的話，日後有人把停用分支改成另一句訊息（例如「此帳號已停用」）
    測試仍會全綠——那一句話就足以讓持有連結的人判斷出帳號狀態，防列舉在重設端破一個洞。
    """
    svc = ResetPasswordService()
    with pytest.raises(AppError) as unknown:
        await svc.reset(db, token="no-such-token-at-all", new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    user = await _make_user(db, user_id="dr", email="dr@edms.local", status="ACTIVE")
    plaintext = await _make_token(db, user_id="dr")
    original_hash = user.pwd_hash
    user.status = "DISABLED"  # 申請之後、重設之前被停用
    await db.flush()

    with pytest.raises(AppError) as disabled:
        await svc.reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)

    got = (disabled.value.status_code, disabled.value.error_code, disabled.value.detail)
    want = (unknown.value.status_code, unknown.value.error_code, unknown.value.detail)
    assert got == want, f"停用={got} 失效token={want}——可據此區分帳號狀態"
    assert got[0] == 400 and got[1] == "DP_PWD_005"

    fresh = (await db.execute(select(DpUser).where(DpUser.user_id == "dr"))).scalar_one()
    assert fresh.pwd_hash == original_hash, "密碼雜湊不得被改動"


async def test_reset_policy_blocked_for_disabled_identical_to_invalid_token(db):
    """`password_rules_for_token` 對停用帳號的回應，與 token 失效**逐字相同**（#953 AC 4）。

    🔴 若兩者分歧（例如停用回一個新的 error_code，或回了門檻數字），持有連結的人就能據此
    判斷「這個帳號被停用了」——防列舉在重設端出現缺口。本條以同一個斷言同時比 status_code、
    error_code 與 detail 文字。
    """
    svc = ResetPasswordService()
    with pytest.raises(AppError) as unknown:
        await svc.password_rules_for_token(db, token="no-such-token-at-all")

    await _make_user(db, user_id="dp2", email="dp2@edms.local", status="DISABLED")
    plaintext = await _make_token(db, user_id="dp2", plaintext="disabled-user-token")
    with pytest.raises(AppError) as disabled:
        await svc.password_rules_for_token(db, token=plaintext)

    got = (disabled.value.status_code, disabled.value.error_code, disabled.value.detail)
    want = (unknown.value.status_code, unknown.value.error_code, unknown.value.detail)
    assert got == want, f"停用={got} 失效token={want}——可據此區分帳號狀態"


async def test_reset_policy_allowed_for_active(db):
    """正向錨點：ACTIVE 帳號的有效 token 仍取得門檻（否則重設頁顯示不出規則提示）。"""
    await _make_user(db, user_id="ap", email="ap@edms.local", status="ACTIVE")
    plaintext = await _make_token(db, user_id="ap", plaintext="active-user-token")
    rules = await ResetPasswordService().password_rules_for_token(db, token=plaintext)
    assert rules.min_len > 0


async def test_shed_503_does_not_consume_reset_token(db, monkeypatch):
    """併發閘卸除（503）不得燒掉使用者的一次性重設連結（#214）。

    `consume_reset_token` 與 `hash_password_async` 之間沒有 commit，故 503 觸發的 rollback
    會一併回復 token。若哪天有人把 consume 提前 commit，這條會紅——那正是要防的回歸：
    使用者收到「系統忙碌中」之後，連結還必須能再用一次。
    """
    from app.core import password_hashing

    await _make_user(db, user_id="shed", email="shed@edms.local")
    plaintext = await _make_token(db, user_id="shed")
    await db.commit()

    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 0)  # 閘位全滿 → 必定卸除
    with pytest.raises(AppError) as err:
        await ResetPasswordService().reset(db, token=plaintext, new_password=_NEW_PWD, confirm_password=_NEW_PWD)
    assert err.value.status_code == 503
    assert err.value.error_code == "COMMON_503"

    await db.rollback()  # production 由 get_db 負責
    token = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "shed"))).scalar_one()
    assert token.used_date is None, "503 之後 token 仍須可用"
    user = (await db.execute(select(DpUser).where(DpUser.user_id == "shed"))).scalar_one()
    assert verify_password(_GOOD_PWD, user.pwd_hash), "503 之後密碼不得被改動"
