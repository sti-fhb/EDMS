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


# ── 端到端：真的打 DM / ET 端點（驗「涵蓋面推導」的前提）──────────────────


#: DM / ET 各取一支走 router-level `get_dm_context` / `get_et_context` 的端點。
_CROSS_MODULE_ENDPOINTS = ["/api/dm/library/documents", "/api/et/my-courses"]


@pytest.mark.parametrize("url", _CROSS_MODULE_ENDPOINTS)
async def test_端到端_跨模組端點對須變更者回403(client, db, url):
    """🔴 本檔其餘測試都是**直接呼叫 dependency 函式**，涵蓋面由 `test_route_auth_coverage.py`
    的結構掃描承擔。那份掃描成立有個前提——**router-level 的 `dependencies=[...]` 真的會
    跑到 `get_jwt_payload`**。前提是從依賴圖「推導」出來的，沒有任何一條測試觀察過。

    本條以真實 ASGI 請求打 DM 與 ET 各一支端點補上那一步。它不是要證明「每支都擋」
    （那是掃描的工作），而是證明**推導所依據的那條鏈實際接得上**。

    📌 受測帳號**不具** DM / ET 任何角色，預期仍是 `DP_AUTH_009` 而非 `DP_AUTH_006`——
    密碼閘排在模組角色閘之前。若日後順序被調換，本條會以 `DP_AUTH_006` 紅掉，那也是
    應該被看見的變化（角色碼會先於密碼狀態洩漏給須變更密碼者）。
    """
    await _make_user(db, user_id="x9", must_change=True)
    token = create_access_token(sub="x9", ttl_minutes=15)
    r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, f"{url} 未擋下須變更密碼者：{r.status_code} {r.text}"
    assert r.json()["error_code"] == "DP_AUTH_009", f"{url} 回的是 {r.json()['error_code']}"


@pytest.mark.parametrize("url", _CROSS_MODULE_ENDPOINTS)
async def test_端到端_密碼正常者不會收到009(client, db, url):
    """正向錨點：少了這條，把閘寫成「一律 403 DP_AUTH_009」也會讓上一條全綠。

    不斷言 200——受測帳號沒有模組角色，本來就可能是 403 `DP_AUTH_006`。
    這裡要的只是「**不是**因為密碼狀態被擋」。
    """
    await _make_user(db, user_id="x8", pwd_changed_days_ago=1)
    token = create_access_token(sub="x8", ttl_minutes=15)
    r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    code = r.json().get("error_code") if r.status_code >= 400 else None
    assert code != "DP_AUTH_009", f"{url} 把密碼正常者也擋成須變更密碼"


# ── AC 3：改完密碼後閘門立即放行 ─────────────────────────────────────


@pytest.mark.parametrize(
    ("must_change", "days_ago"), [(True, 1), (False, 91)], ids=["旗標為真", "逾效期"]
)
async def test_改完密碼後閘門立即放行(client, db, must_change, days_ago):
    """AC 3 的**合成**驗證：擋下 → 改密碼 → 放行，一條測試走完整條因果鏈。

    🔴 為什麼不靠既有的兩條分頭守：`test_dp_user_profile.py` 守「改密碼會清旗標」、
    本檔參數化守「旗標為 False 就放行」，但**沒有人驗兩者接得上**。本 PR 把「漏擋」換成
    「全擋」，因果鏈的終點因此改變了性質——清旗標那一步若失靈，後果不再是某支端點行為
    怪怪的，而是**每個密碼逾期帳號永久鎖死整個系統**（連改密碼頁都進不去的下一步）。
    這個後果是本 PR 新造的，證據就該在本 PR。

    📌 第 3 步必須**重新登入**：#941 之後，變更前簽發的 token 一律失效。AC 3 原文寫
    「改完密碼後立即可正常使用」，實際語意是「以新密碼重登後立即可用」——同一工作階段
    延續的那個讀法在 #941 已經不成立。

    📌 **兩種進入狀態都要走一次**：旗標為真只發生在 `edmsops`（全專案唯一把
    `MUST_CHANGE_PWD` 設為 true 的地方是 vendor ops 的 seed migration），一般帳號走的是
    逾效期。兩者的脫困條件不同——前者靠清旗標、後者靠更新 `PWD_CHANGED_DATE`，
    只測旗標那一種，逾期帳號能不能出得來是沒驗過的。
    """
    uid = f"ac3{int(must_change)}"
    await _make_user(db, user_id=uid, must_change=must_change, pwd_changed_days_ago=days_ago)

    # ① 改密碼前：閘門擋下
    old_token = create_access_token(sub=uid, ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(old_token), db=db)
    assert exc.value.error_code == "DP_AUTH_009"

    # ② 以豁免端點改密碼——使用者脫困的唯一路徑
    r = await client.put(
        "/api/dp/user/me/password",
        headers={"Authorization": f"Bearer {old_token}"},
        json={"old_password": "Abcd1234", "new_password": "Zyxw4321", "confirm_password": "Zyxw4321"},
    )
    assert r.status_code == 204, f"改密碼失敗，使用者將永遠出不來：{r.status_code} {r.text}"

    # ③ 以新密碼重新登入
    r = await client.post("/api/login", json={"email": f"{uid}@edms.local", "password": "Zyxw4321"})
    assert r.status_code == 200, r.text
    assert r.json()["must_change_pwd"] is False, "改完密碼登入仍要求變更，使用者會卡在迴圈"

    # ④ 閘門放行（`expire_on_commit=False`，重查前先讓既載入的實體過期）
    db.expire_all()
    payload = await get_jwt_payload(credentials=_creds(r.json()["access_token"]), db=db)
    assert payload.sub == uid
