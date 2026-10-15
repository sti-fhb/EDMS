"""#74 驗證信寄送冷卻——router 接線整合測試。

驗「接線」：register / resend 兩端點確實掛上共用冷卻（check 前置、record 後置）、
429 帶 retry_after、防列舉、共用額度、register 檢核失敗不誤觸冷卻。
冷卻邏輯本身的邊界（剩餘秒計算、視窗刷新等）已由 tests/unit/test_core_cooldown.py 覆蓋。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.user import router as auth_router
from app.dp.user.models import DpPendingRegistration
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


@pytest.fixture(autouse=True)
def _reset_limits():
    """清除 module-level 冷卻器與相關限流器狀態，隔離跨測試污染（單例會殘留）。"""
    auth_router._verify_send_cooldown._last.clear()
    # #234 新增的單例：它跨測試存活（24 小時視窗），不清會讓第 5 次起的同 Email
    # 註冊落入靜默路徑——而那條路徑回 202、不報錯，測試可能**為了錯的理由通過**。
    auth_router._overwrite_counter._hits.clear()
    auth_router._register_limiter._hits.clear()
    auth_router._resend_limiter._hits.clear()
    yield


def _reg_payload(email: str, **over):
    base = {"email": email, "user_name": "冷卻測試"}
    base.update(over)
    return base


async def test_resend_success_carries_retry_after(client):
    """首次重寄 → 200，回應帶 retry_after（＝完整冷卻秒數，預設 600）供前端起算倒數。"""
    r = await client.post("/api/resend-verification", json={"email": "cool-a@edms.local"})
    assert r.status_code == 200
    body = r.json()
    assert body["retry_after"] == 600  # DP_PARAM 未設 → 預設 600


async def test_resend_within_cooldown_429_even_for_unknown_email(client):
    """冷卻內第二次重寄 → 429 COMMON_429 帶 retry_after；且對「不存在的 Email」同樣 429（防列舉）。

    cool-b 從未註冊（無待驗證列），仍在第二次被擋 → 證明 429 不因帳號存在與否而異。
    """
    first = await client.post("/api/resend-verification", json={"email": "cool-b@edms.local"})
    assert first.status_code == 200

    second = await client.post("/api/resend-verification", json={"email": "cool-b@edms.local"})
    assert second.status_code == 429
    body = second.json()
    assert body["error_code"] == "COMMON_429"
    assert 1 <= body["retry_after"] <= 600


async def test_register_and_resend_share_cooldown_budget(client):
    """register 與 resend 共用同一 Email 冷卻額度：註冊後立即重寄同 Email → 429（堵繞道）。"""
    reg = await client.post("/api/register", json=_reg_payload("cool-c@edms.local"))
    assert reg.status_code == 202
    assert reg.json()["retry_after"] == 600

    resend = await client.post("/api/resend-verification", json={"email": "cool-c@edms.local"})
    assert resend.status_code == 429
    assert resend.json()["error_code"] == "COMMON_429"


async def test_register_silent_path_does_not_stamp_email_cooldown(client, db, as_ip):
    """未寄信的註冊**不得留下 Email 章**；隨後他人對同 Email 仍可正常寄送。

    觸發條件換過三次：原以「弱密碼 422」，#212 之後註冊不收密碼而改用「未逾期的管理者邀請」
    （當時回 `DP_USER_011`，位置在冷卻 check **之後**）；#208 把該檢核前移到冷卻 check 之前；
    **#345 再把它從 409 改成靜默 202**——受邀者離開 409 集合才能關掉交叉比對的列舉面。

    ⚠️ 性質也隨之精確化。舊版寫「不得留下冷卻章」，但靜默路徑**會**蓋 `probe` 章
    （IP x Email，只影響發起者自己，用來讓「同一 IP 連打」的回應與全新 Email 對齊）。
    真正不得留下的是 **Email 章**（`verify-send:acct:`）——那把章跨 IP，留下來就等於
    任何匿名者打一次註冊就能封鎖他人 600 秒，正是 #213 修掉的那條路。

    故驗法改為**換一個 IP 去 resend**：`probe` 章與新 IP 無關，若此時被擋，只可能是
    Email 章被蓋了。
    """
    email = "cool-invite@edms.local"
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token("invite-cool"),
            email=email,
            user_name="被邀請者",
            pwd_hash=None,
            kind="ADMIN_INVITE",
            invite_id="INVCOOL0001",
            expires_date=now + timedelta(hours=24),
            created_user="admin01",
            created_date=now,
        )
    )
    await db.commit()

    as_ip("203.0.113.9")
    silent = await client.post("/api/register", json=_reg_payload(email))
    assert silent.status_code == 202, "#345：未逾期邀請改為與全新 Email 同形的靜默 202"

    # 換一個 IP：probe 章與它無關，若此時被擋就代表 Email 章被蓋了（#213 的封鎖向量）
    as_ip("198.51.100.7")
    resend = await client.post("/api/resend-verification", json={"email": email})
    assert resend.status_code == 200, "靜默路徑不得蓋 Email 章——否則匿名者可封鎖他人 600 秒"


async def test_verified_email_returns_409_even_within_cooldown(client, db):
    """#86：已驗證帳號在冷卻內再註冊（含大小寫變體）→ 立即 409 DP_USER_001，不回 429、無倒數。

    「已是正式帳號」是終局狀態，等冷卻結束也不會改變；且此路徑本來就不送信，
    冷卻在此無防狂發價值，只會讓使用者白等一輪才被告知「已被註冊」。
    """
    email = "verified-user@edms.local"
    now = utcnow()
    db.add(
        DpUser(
            user_id="U0000000000000000001",
            email=email,
            pwd_hash=hash_password("Abcd1234"),
            user_name="已驗證使用者",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="SYSTEM",
            created_date=now,
        )
    )
    await db.commit()

    # 該 Email 的驗證信冷卻仍有效（例如當初 pending 階段剛寄過）
    auth_router._verify_send_cooldown.record(auth_router._verify_send_key(email))

    r = await client.post("/api/register", json=_reg_payload("VERIFIED-USER@edms.local"))
    assert r.status_code == 409
    body = r.json()
    assert body["error_code"] == "DP_USER_001"
    assert "retry_after" not in body


async def test_new_email_still_blocked_by_cooldown(client):
    """#86 的順序調整不影響防狂發：全新 / pending Email 於冷卻內再註冊仍為 429 + retry_after。"""
    first = await client.post("/api/register", json=_reg_payload("cool-e@edms.local"))
    assert first.status_code == 202

    second = await client.post("/api/register", json=_reg_payload("cool-e@edms.local"))
    assert second.status_code == 429
    body = second.json()
    assert body["error_code"] == "COMMON_429"
    assert 1 <= body["retry_after"] <= 600


# ─────────────────────────────────────────────────────────────────────────────
# #213：只在真的寄出信時蓋 Email 章；沒寄信只蓋「發起者自己」的章
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def as_ip(monkeypatch):
    """切換 router 眼中的 client IP（`_verify_send_probe_key` 用它分桶）。

    ASGI 測試傳輸沒有真實 peer 位址，且 XFF 預設不受信（TRUSTED_PROXY_COUNT=0，#23），
    故直接替換 router 模組內的 `get_client_ip` 名稱——只影響本 key 函式，不動限流器自己的取值。
    """

    def _set(ip: str) -> None:
        monkeypatch.setattr(auth_router, "get_client_ip", lambda: ip)

    return _set


async def test_probe_by_attacker_does_not_block_victim_registration(client, as_ip):
    """**本 issue 的核心**：匿名者對他人 Email 打 resend 後，該他人仍可正常完成自助註冊（#213）。

    改動前 resend 是無條件蓋 Email 章，而它對「查無待驗證列」是靜默不寄 → 攻擊者打一次就替任意
    Email 蓋 600 秒章，且該 key 與 register 共用 → 受害者註冊得到 429「操作過於頻繁」，每 10 分鐘
    重打一次即可無限期封鎖。無稽核、無寄信紀錄、狀態只在行程記憶體。
    """
    email = "victim@edms.local"

    as_ip("203.0.113.9")  # 攻擊者
    probe = await client.post("/api/resend-verification", json={"email": email})
    assert probe.status_code == 200  # 回應與「有寄出」完全相同（防列舉）

    as_ip("198.51.100.7")  # 受害者，不同 IP
    reg = await client.post("/api/register", json=_reg_payload(email))
    assert reg.status_code == 202  # 未被攻擊者的探測波及


async def test_probe_still_blocks_the_prober_itself(client, as_ip):
    """同一發起者重打 → 仍 429（形狀與有寄出時相同），故單一 IP 下問不出存在性。"""
    email = "prober@edms.local"
    as_ip("203.0.113.9")

    first = await client.post("/api/resend-verification", json={"email": email})
    assert first.status_code == 200

    second = await client.post("/api/resend-verification", json={"email": email})
    assert second.status_code == 429
    assert second.json()["error_code"] == "COMMON_429"


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(None, id="無待驗證列"),
        pytest.param("SELF_REGISTER", id="有自助註冊列"),
        pytest.param("ADMIN_INVITE", id="有管理者邀請列"),
    ],
)
async def test_same_ip_429_identical_regardless_of_pending_state(client, db, as_ip, seed):
    """同一 IP 下，429 的有無與內容**不因該 Email 的待驗證狀態而異**（防列舉語意不退化）。

    三種狀態中只有 SELF_REGISTER 會真的寄信（走 Email 章），另兩種靜默不寄（走 probe 章），
    但發起者看到的第二次回應完全相同。
    """
    email = f"enum-{seed}@edms.local"
    if seed is not None:
        now = utcnow()
        db.add(
            DpPendingRegistration(
                token_hash=hash_token(f"enum-{seed}"),
                email=email,
                user_name="待驗證",
                pwd_hash=None,
                kind=seed,
                invite_id="INVENUM0001" if seed == "ADMIN_INVITE" else None,
                expires_date=now + timedelta(minutes=30),
                created_user="seed",
                created_date=now,
            )
        )
        await db.commit()

    as_ip("203.0.113.50")
    first = await client.post("/api/resend-verification", json={"email": email})
    second = await client.post("/api/resend-verification", json={"email": email})

    assert first.status_code == 200
    assert first.json()["retry_after"] == 600
    assert second.status_code == 429
    assert second.json()["error_code"] == "COMMON_429"


async def test_real_resend_still_cooled_across_ips(client, db, as_ip):
    """對同一 Email 的**真實**重寄仍受 Email 維度冷卻約束（防狂發不變，且跨 IP 有效）。

    這條是候選 1（key 加 IP 維度）被否決的原因：那個做法會讓換 IP 就能對同一信箱無限發信，
    而 register 是匿名端點——把「封鎖某人註冊」換成「用組織自己的網域對某人信箱轟炸」。

    ## ⚠️ #345 起改用**副作用**驗，不再驗狀態碼——性質沒放棄，是換了手段

    原本斷言跨 IP 第二次回 **429**。但那個 429 把「有沒有 acct 章」跨 IP 洩漏了出去，而
    acct 章只在真的寄出時蓋（#213）⇒ 它等同於「register 剛才是真寄還是靜默」⇒
    「這個 Email 是不是受邀者」。兩個請求即可決定性取出邀請名單，與 #345 原本要修的殘留同級。

    改為：仍然**不寄**（防轟炸的目的原封不動），但回 200 靜默。本測試因此改成斷言
    **outbox 沒有新增列**——那才是「不得對同一信箱無限發信」的直接證據；狀態碼只是它
    先前的代理指標，而那個代理指標本身是個 oracle。

    ⛔ 日後若有人想把 429 加回來「讓使用者知道在冷卻中」，請先讀上面這段：使用者自己的
    冷卻**仍然**回 429（走 probe 章），回 429 的只能是自己那一層。
    """
    email = "realresend@edms.local"
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token("realresend"),
            email=email,
            user_name="待驗證",
            pwd_hash=None,
            kind="SELF_REGISTER",
            expires_date=now + timedelta(minutes=30),
            created_user="seed",
            created_date=now,
        )
    )
    await db.commit()

    as_ip("203.0.113.1")
    first = await client.post("/api/resend-verification", json={"email": email})
    assert first.status_code == 200  # 真的寄出 → 蓋 Email 章

    sent_after_first = await db.scalar(
        select(func.count()).select_from(DpEmailLog).where(DpEmailLog.recipient == email)
    )
    assert sent_after_first == 1, "前提錨點：第一次確實寄出了，否則下面的『沒有第二封』恆真"

    as_ip("203.0.113.2")  # 換 IP
    second = await client.post("/api/resend-verification", json={"email": email})

    assert second.status_code == 200, "#345：他人的 Email 章改為靜默，429 會洩漏該章的有無"
    sent_after_second = await db.scalar(
        select(func.count()).select_from(DpEmailLog).where(DpEmailLog.recipient == email)
    )
    assert sent_after_second == 1, "跨 IP **仍然不得真的再寄一封**——防轟炸的目的不變"


async def test_resend_cross_ip_response_does_not_reveal_email_stamp(client, db, as_ip):
    """#345 Security HIGH-1：register -> resend 的兩請求 oracle 已關閉。

    攻擊路徑（改動前成立、實測過）：

    | | register（IP1）| resend（IP2）| outbox |
    |---|---|---|---|
    | 受邀者 | 202 | **200** | 0 |
    | 全新 | 202 | **429** | 1 |

    兩個請求、決定性，且**命中時完全無聲**（兩步都不寄信，受害者與系統都沒有痕跡）——
    噪音只出現在「猜錯」的那一半，正是攻擊者不在意的那一半。
    """

    async def probe(email: str) -> tuple[int, int]:
        as_ip("203.0.113.1")
        await client.post("/api/register", json=_reg_payload(email))
        as_ip("203.0.113.2")
        r = await client.post("/api/resend-verification", json={"email": email})
        return r.status_code, r.json()["retry_after"]

    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token("h1-invite"),
            email="h1-invited@edms.local",
            user_name="受邀者",
            pwd_hash=None,
            kind="ADMIN_INVITE",
            invite_id="INVH1000001",
            expires_date=now + timedelta(hours=24),
            created_user="admin01",
            created_date=now,
        )
    )
    await db.commit()

    invited = await probe("h1-invited@edms.local")
    fresh = await probe("h1-fresh@edms.local")

    assert invited == fresh, f"受邀者與全新 Email 的 resend 回應必須相同；實得 {invited} vs {fresh}"
