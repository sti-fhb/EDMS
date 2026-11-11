"""強制變更密碼閘整合測試：MUST_CHANGE_PWD 旗標 / 密碼逾效期 → 403 DP_AUTH_009。

#929 起本閘由 `get_jwt_payload` 內建（原先的 `require_password_current` 只掛在一支端點上，
其餘 DP 後台 / DM / ET 的 API 完全沒擋）。白名單端點改用 `get_jwt_payload_pwd_exempt`。
"""

from datetime import timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import (
    create_access_token,
    ensure_password_current,
    get_jwt_payload,
    get_jwt_payload_pwd_exempt,
)
from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, *, user_id, must_change=False, pwd_changed_days_ago=1):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=f"{user_id}@edms.local",
        pwd_hash=hash_password("Abcd1234"),
        user_name="閘測試",
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


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── 判定本身（以已載入的 DpUser 判，不再自行查庫）────────────────────────


async def test_判定_密碼現行有效者放行(db):
    """旗標 False + 未逾效期 → 不拋。"""
    user = await _make_user(db, user_id="cur", pwd_changed_days_ago=1)
    await ensure_password_current(db, user)  # 不拋即通過


async def test_判定_MUST_CHANGE_PWD為真者擋下(db):
    user = await _make_user(db, user_id="mc", must_change=True)
    with pytest.raises(AppError) as exc:
        await ensure_password_current(db, user)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_009"


async def test_判定_密碼逾效期者擋下(db):
    """種子 EXPIRY_DAYS=90。"""
    user = await _make_user(db, user_id="exp", pwd_changed_days_ago=91)
    with pytest.raises(AppError) as exc:
        await ensure_password_current(db, user)
    assert exc.value.error_code == "DP_AUTH_009"


# ── 掛載：預設擋、豁免版放行（#929）─────────────────────────────────


async def test_預設閘擋下須變更密碼者(db):
    """`get_jwt_payload` 是全站必經之路，須變更密碼者在此即被擋。"""
    await _make_user(db, user_id="gate1", must_change=True)
    token = create_access_token(sub="gate1", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_009"


async def test_豁免版放行須變更密碼者(db):
    """白名單端點（改密碼 / 讀個資 / 換發 / 登出）用豁免版——擋了就沒人出得來。

    🔴 這條與上一條**必須成對**：只有上一條的話，把豁免版也寫成會擋的實作一樣全綠，
    而那會讓須變更密碼的帳號連改密碼都做不到，整個帳號廢掉。
    """
    await _make_user(db, user_id="gate2", must_change=True)
    token = create_access_token(sub="gate2", ttl_minutes=15)
    payload = await get_jwt_payload_pwd_exempt(credentials=_creds(token), db=db)
    assert payload.sub == "gate2"


async def test_豁免版仍檢查帳號狀態(db):
    """豁免的只有「密碼狀態」，停用 / 鎖定 / 已刪仍必須擋下。

    ⚠️ 少了這條，把豁免版寫成「完全不查 DP_USER」也會讓上一條通過——那等於在白名單端點
    上開了一個不驗帳號狀態的洞。
    """
    user = await _make_user(db, user_id="gate3", must_change=True)
    user.status = "DISABLED"
    await db.flush()
    token = create_access_token(sub="gate3", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload_pwd_exempt(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_004"


@pytest.mark.parametrize(
    ("must_change", "days_ago", "expect_blocked"),
    [(True, 1, True), (False, 91, True), (False, 1, False), (False, 90, True), (False, 89, False)],
    ids=["旗標為真", "逾效期", "正常", "剛好滿90天", "89天"],
)
async def test_登入回應與閘門判定一致(client, db, must_change, days_ago, expect_blocked):
    """登入回的 `must_change_pwd` 必須與閘門是否擋下**完全一致**（#929）。

    🔴 兩者共用 `must_change_password` 之後算式必然相同，但**接線**可能漂移——例如日後有人
    在登入端補了額外條件、或閘門改成只看旗標。那時使用者會卡在兩種狀態之一：
    登入說要改但閘不擋（看到強制變更頁卻能繞過），或登入說不用改但閘一直擋（改完仍進不去）。
    本條以同一個帳號同時走兩條路，兩邊不一致即紅。
    """
    uid = f"sync{days_ago}{int(must_change)}"
    user = await _make_user(db, user_id=uid, must_change=must_change, pwd_changed_days_ago=days_ago)
    user.pwd_hash = hash_password("Abcd1234")
    await db.flush()

    r = await client.post("/api/login", json={"email": f"{uid}@edms.local", "password": "Abcd1234"})
    assert r.status_code == 200, r.text
    login_says = r.json()["must_change_pwd"]

    token = create_access_token(sub=uid, ttl_minutes=15)
    try:
        await get_jwt_payload(credentials=_creds(token), db=db)
        gate_blocked = False
    except AppError as exc:
        assert exc.error_code == "DP_AUTH_009"
        gate_blocked = True

    assert login_says == gate_blocked == expect_blocked, (
        f"登入回 {login_says}、閘門擋下 {gate_blocked}、預期 {expect_blocked}——兩條路已漂移"
    )


async def test_密碼現行有效者兩版皆放行(db):
    """正向錨點：未處於須變更狀態者不受本次變更影響。"""
    await _make_user(db, user_id="ok1", pwd_changed_days_ago=1)
    token = create_access_token(sub="ok1", ttl_minutes=15)
    assert (await get_jwt_payload(credentials=_creds(token), db=db)).sub == "ok1"
    assert (await get_jwt_payload_pwd_exempt(credentials=_creds(token), db=db)).sub == "ok1"
