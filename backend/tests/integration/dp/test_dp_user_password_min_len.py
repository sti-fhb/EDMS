"""管理者密碼長度門檻（#623）：忘記密碼重設比照變更密碼套 12 字元，並提供「本人適用規則」端點。

兩支端點的用途是讓前端提示與前端檢核用**同一個**門檻：原本前端只讀公開政策的 `min_len`
（一般門檻），管理者照提示設 8～11 字元，送出才被後端擋下。
"""

from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.password_policy import hash_password, verify_password
from app.core.utils import utcnow
from app.dp.params.models import DpParamDetail
from app.dp.user.forgot_service import ResetPasswordService
from app.dp.user.models import DpPwdReset
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser
from app.et.roles.gate import et_is_module_admin

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"
_NINE = "Abcd1234!"  # 9 字元、4 種字元：一般使用者合規，管理者長度不足
_TWELVE = "Abcd1234efg!"


@contextmanager
def _as_et_admin(*user_ids):
    """暫時讓指定使用者成為 ET 管理者。

    ⚠️ 結束時**還原為真實判定**而非 `unregister`：main.py 啟動即註冊 ET 判定，`unregister`
    會留下正式環境不存在的「沒有 ET 判定」狀態，污染同 worker 後續測試（比照
    `integration/conftest.py` 的 `backoffice_admin`）。
    """

    async def _checker(_db, user_id):
        return user_id in user_ids

    module_admin_gate.register("ET", _checker)
    try:
        yield
    finally:
        module_admin_gate.register("ET", et_is_module_admin)


async def _make_user(db, user_id, *, must_change=False, pwd_age_days=1):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password(_GOOD_PWD),
            user_name="門檻測試",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now - timedelta(days=pwd_age_days),
            must_change_pwd=must_change,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


async def _make_reset_token(db, user_id, plaintext, *, minutes=30, used=False):
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


def _bearer(user_id):
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


# --- AC 3 / AC 4：忘記密碼重設 ---


async def test_管理者以忘記密碼重設_9字元被擋_12字元通過(db):
    await _make_user(db, "rsadm")
    token = await _make_reset_token(db, "rsadm", "tok-admin")
    with _as_et_admin("rsadm"):
        with pytest.raises(AppError) as exc:
            await ResetPasswordService().reset(db, token=token, new_password=_NINE, confirm_password=_NINE)
        assert exc.value.error_code == "DP_PWD_001"
        await ResetPasswordService().reset(db, token=token, new_password=_TWELVE, confirm_password=_TWELVE)
    user = await db.get(DpUser, "rsadm")
    assert verify_password(_TWELVE, user.pwd_hash)


async def test_一般使用者以忘記密碼重設_9字元通過(db):
    await _make_user(db, "rsusr")
    token = await _make_reset_token(db, "rsusr", "tok-user")
    with _as_et_admin("someone-else"):
        await ResetPasswordService().reset(db, token=token, new_password=_NINE, confirm_password=_NINE)
    user = await db.get(DpUser, "rsusr")
    assert verify_password(_NINE, user.pwd_hash)


# --- AC 1 / AC 2 / AC 4：登入者本人適用規則 ---


async def test_本人規則端點_管理者回12_一般回8(client, db):
    await _make_user(db, "meadm")
    await _make_user(db, "meusr")
    with _as_et_admin("meadm"):
        admin = await client.get("/api/dp/user/me/password-policy", headers=_bearer("meadm"))
        user = await client.get("/api/dp/user/me/password-policy", headers=_bearer("meusr"))
    assert admin.status_code == 200 and admin.json() == {"min_len": 12, "char_types": 3}
    assert user.status_code == 200 and user.json() == {"min_len": 8, "char_types": 3}


async def test_本人規則端點_密碼到期者仍可取得(client, db):
    """強制變更密碼畫面要靠它顯示門檻，故不得被密碼閘擋下（對照組：module-summary 會被擋）。"""
    await _make_user(db, "meexp", pwd_age_days=400)
    with _as_et_admin("meexp"):
        r = await client.get("/api/dp/user/me/password-policy", headers=_bearer("meexp"))
        gated = await client.get("/api/dp/user/module-summary", headers=_bearer("meexp"))
    assert gated.status_code == 403  # 證明此帳號確實處於被密碼閘擋下的狀態
    assert r.status_code == 200 and r.json()["min_len"] == 12


async def test_本人規則端點_未登入回401(client):
    r = await client.get("/api/dp/user/me/password-policy")
    assert r.status_code == 401


# --- AC 3 / AC 4：重設頁（未登入，以 token 識別）---


async def test_重設規則端點_依token帳號回門檻(client, db):
    await _make_user(db, "tkadm")
    await _make_user(db, "tkusr")
    await _make_reset_token(db, "tkadm", "tok-policy-admin")
    await _make_reset_token(db, "tkusr", "tok-policy-user")
    with _as_et_admin("tkadm"):
        admin = await client.post("/api/reset-password/policy", json={"token": "tok-policy-admin"})
        user = await client.post("/api/reset-password/policy", json={"token": "tok-policy-user"})
    assert admin.status_code == 200 and admin.json() == {"min_len": 12, "char_types": 3}
    assert user.status_code == 200 and user.json() == {"min_len": 8, "char_types": 3}


# 失效 token 的回應**逐欄位固定**為這一組。下面四條（無此列 / 逾期 / 已用 × 管理者 / 一般）
# 全部斷言同一個字面量——相同的期望值即「失效 token 不依帳號判定」的斷言本身。
#
# ⛔ **不要改寫成「在同一條測試裡打管理者與一般兩次、比對兩個回應相等」**：失敗的請求會讓
# integration 的前置資料回滾，第二次呼叫將查無該列而「因為另一個理由」回同樣的答案——
# 那樣寫**拿掉修法也會通過**。一條測試只安排一次預期失敗的呼叫。
_DEAD_LINK = {"error_code": "DP_PWD_005", "error_message": "連結已失效，請重新申請"}


async def test_重設規則端點_查無token回連結已失效(client, db):
    """#673：失效連結 MUST 於**點連結時**即拒絕（spec_us3 AC 3），不再回門檻讓表單渲染。"""
    r = await client.post("/api/reset-password/policy", json={"token": "no-such-token"})
    assert r.status_code == 400
    assert r.json() == _DEAD_LINK


@pytest.mark.parametrize(("minutes", "used"), [(-1, False), (30, True)], ids=["逾期", "已用過"])
@pytest.mark.parametrize("is_admin", [True, False], ids=["管理者", "一般使用者"])
async def test_重設規則端點_失效token的回應不因是否為管理者而異(client, db, minutes, used, is_admin):
    """⛔ 失效 token 不得依其帳號判定——否則端點會替已作廢的連結報出「這是管理者」。

    #673 把失效的回應從「200 + 一般門檻」改為「400 DP_PWD_005」，**此不變量不變**：
    四個組合都斷言同一個 `_DEAD_LINK` 字面量，管理者與一般使用者的失效連結逐欄位相同。
    """
    await _make_user(db, "tkdead")
    await _make_reset_token(db, "tkdead", "tok-dead", minutes=minutes, used=used)
    admins = ("tkdead",) if is_admin else ()
    with _as_et_admin(*admins):
        r = await client.post("/api/reset-password/policy", json={"token": "tok-dead"})
    assert r.status_code == 400
    assert r.json() == _DEAD_LINK


# --- AC 5：參數調整後跟著變 ---


async def test_調整_ADMIN_MIN_LEN_後端點回新值(client, db):
    await _make_user(db, "pradm")
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "PWD_POLICY", DpParamDetail.param_key == "ADMIN_MIN_LEN")
        .values(param_value="14")
    )
    await db.flush()
    with _as_et_admin("pradm"):
        r = await client.get("/api/dp/user/me/password-policy", headers=_bearer("pradm"))
    assert r.json()["min_len"] == 14
