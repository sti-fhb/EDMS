"""匿名註冊端點不得單獨揭露「管理者邀請」（#208 範圍補充留言）。

## 為什麼修完 login 還不夠

#208 的驗收條件是**端點範圍**的（「打 `/api/login` … 無法區分待驗證列的有無」）。但
`register_service` 的 `DP_USER_011` 是全系統唯一會單獨揭露 pending 列 `KIND` 的訊號——
login 收斂之後，攻擊者仍可從 `/api/register` 分辨出「這個 Email 是**管理者發出的邀請**」，
而那正是最有價值的一格。

程式碼註解早就寫明措辭上的謹慎（「刻意不提『管理者邀請』…該句型亦常被釣魚信複用」），
但 `app_error_handler` 會把 `error_code` 一起放進回應本體。`DP_USER_011` 是有文件的穩定代碼、
語意就是「管理者邀請未逾期」——**文案上的模糊只對人類有效，對腳本一清二楚**。

攻擊價值具體而非抽象：以組織 Email 命名規則產生候選清單逐一探測，命中者就是「此刻正在等
一封啟用信、還沒設過密碼」的人。對這批人發仿冒的啟用信成功率遠高於盲發——他們真的在等
這封信，而且沒有既有密碼可比對、更難察覺異常。

## 收斂到什麼程度（#345 / #346 之後）

`register` 的 409 現在**恰好等於**「`DP_USER` 列存在」，與 login 的
`DP_AUTH_004 / 005 / 008` 同一集合——交叉比對因此不再產生新資訊。

未逾期的 `ADMIN_INVITE`（#345）與「他人冷卻中」（#346）都改回與全新 Email **同形的 202**，
且**完全不寫入任何東西**（不寄信、不覆蓋、不換 token、不蓋 Email 冷卻章）。

```
① POST /api/login（密碼任意）→ DP_AUTH_007  ⇒ 無未刪除的 DP_USER 列
② POST /api/register          → 409         ⇒ DP_USER 列存在
①∩② = ∅
```

⚠️ **刻意保留、未關閉的一格**：`DP_AUTH_008` 與 `DP_AUTH_007` 仍可區分「某 Email 是否為
已驗證帳號」——#208 AC 2 明訂保留（鎖定計數與既有 UX 掛在該路徑）。若日後要併掉它，
**必須同時補 dummy password verify**，理由見 `dp/user/service.py::login()` 的 docstring。

⚠️ **register 的 429 仍存在，但只對「自己」**：同一 IP × Email 的 `probe` 章會明說 429
（防狂發），他人蓋的 Email 章則是靜默 202。兩層 key 的語意見
`router.py::_verify_send_probe_key`（#213 建立、#346 擴及 register）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user import router as auth_router
from app.dp.user.kinds import KIND_ADMIN_INVITE
from app.dp.user.models import DpPendingRegistration
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_limits():
    """冷卻器與限流器是 module-level 單例，跨測試會殘留。"""
    auth_router._verify_send_cooldown._last.clear()
    auth_router._register_limiter._hits.clear()
    auth_router._resend_limiter._hits.clear()
    yield


async def _verified_user(db, *, user_id: str, email: str) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash=hash_password("Abcd1234"),
            user_name="已驗證",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _admin_invite(db, *, email: str, hours: int = 24) -> None:
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token(f"invite-{email}"),
            email=email,
            user_name="受邀者",
            pwd_hash=None,
            kind=KIND_ADMIN_INVITE,
            invite_id=f"INV{abs(hash(email)) % 10**8:08d}",
            expires_date=now + timedelta(hours=hours),
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


@pytest.fixture
def as_ip(monkeypatch):
    """切換 router 眼中的 client IP（`_verify_send_probe_key` 用它分桶）。

    ⚠️ ASGI 測試傳輸沒有真實 peer 位址，且 `X-Forwarded-For` 預設**不受信**
    （`TRUSTED_PROXY_COUNT=0`，#23）——送那個 header 不會改變 probe key。寫法比照
    `test_dp_user_resend_cooldown.py` 的同名 fixture：直接替換 router 模組內的
    `get_client_ip` 名稱，只影響本 key 函式、不動限流器自己的取值。
    """

    def _set(ip: str) -> None:
        monkeypatch.setattr(auth_router, "get_client_ip", lambda: ip)

    return _set


def _payload(email: str) -> dict:
    return {"email": email, "user_name": "探測者"}


def _signature(resp) -> tuple[int, str | None, str | None]:
    body = resp.json()
    return (resp.status_code, body.get("error_code"), body.get("error_message"))


async def test_已受邀與全新_email_的註冊回應完全一致(client, db) -> None:
    """#345 的核心：受邀者改與**全新 Email** 同形，而不是與「已註冊」同形。

    ⚠️ 本條的前身是 `test_已受邀與已註冊的註冊回應完全一致`（#208）——那時的正確行為是
    「受邀 ≡ 已註冊」。#345 把它**反轉**了：讓受邀者離開 409 集合，409 才會恰好等於
    「`DP_USER` 列存在」，與 login 的 004/005/008 同一集合，交叉比對因此失效。

    必須在同一條裡比對**整包回應**（status + body）：分開斷言「各自回 202」會全綠卻驗不到
    重點——只要有人日後為了 UX 把其中一條的訊息岔開，列舉面就回來了，而兩條各自的斷言
    都還會過。⭐ 文案維持原文（2026-10-13 裁示）之後，這條是唯一守住該性質的測試。
    """
    await _admin_invite(db, email="invited@edms.local")
    await db.commit()

    invited = await client.post("/api/register", json=_payload("invited@edms.local"))
    fresh = await client.post("/api/register", json=_payload("brand-new@edms.local"))

    assert invited.status_code == 202, invited.text
    assert invited.json() == fresh.json(), "『已受邀』不得與『全新 Email』區分開來"


async def test_已註冊仍回_409_與_login_同一集合(client, db) -> None:
    """#345 刻意**不**收斂的那一格：已驗證帳號本來就是公開可探測的（#208 AC 2 明訂保留）。

    正向錨點——少了這條，把 409 整個拿掉也能讓上面那條全綠，而那會連「已註冊」的
    既有 UX（直接登入 / 忘記密碼）一起拆掉。
    """
    await _verified_user(db, user_id="u_reg_enum", email="registered@edms.local")
    await db.commit()

    registered = await client.post("/api/register", json=_payload("registered@edms.local"))

    assert registered.status_code == 409, registered.text
    assert registered.json()["error_code"] == "DP_USER_001"


async def test_統一訊息同時鋪出登入與收信兩條路(client, db) -> None:
    """受邀者沒有 `DP_USER` 列，忘記密碼對他是防列舉的靜默 no-op。

    舊的 `_EMAIL_TAKEN_MSG` 只寫「請直接登入或使用忘記密碼」，受邀者照著做會走進死路——
    所以合併之後訊息**必須**同時提到「收到的啟用 / 驗證信」這條路。

    ⚠️ #345 之後受邀者已不走 409（改為靜默 202），本條改以**已註冊** Email 取樣。訊息本身
    一字未改、三條出路的要求仍然成立——已註冊者也可能曾收過驗證信（註冊後、驗證前那段）。
    """
    await _verified_user(db, user_id="u_guide", email="guide@edms.local")
    await db.commit()

    message = (await client.post("/api/register", json=_payload("guide@edms.local"))).json()["error_message"]

    assert "登入" in message, "已註冊者要知道可以直接登入"
    assert "忘記密碼" in message, "已註冊者要知道可以自助重設"
    assert "信" in message and "連結" in message, "受邀者唯一走得通的是點信裡的連結"


@pytest.mark.parametrize("state", ["registered", "invited"])
async def test_冷卻武裝時仍回終局狀態而非429(client, db, state: str) -> None:
    """位置差也是 oracle：若一個擋在冷卻前、一個擋在冷卻後，武裝時會變成 409 vs 429。

    ⚠️ **冷卻 key 是 `verify-send:acct:{email}`，必須武裝到「被測的那個 Email」。**
    先前這條測試以另一個 Email 成功註冊來「武裝冷卻」，但那只蓋了那個 Email 的章，被測
    Email 的 key 從未被蓋——於是把檢核移回冷卻之後（本條要防的回歸）它仍會全綠，等於沒有守衛。
    現改為：先對**同一個** Email 成功註冊（真的寄出 → 蓋章），再讓它變成不可用狀態。

    這也對應真實情境：使用者自助註冊後 600 秒內完成驗證或收到邀請，冷卻章仍在。
    """
    email = f"armed-{state}@edms.local"

    primed = await client.post("/api/register", json=_payload(email))
    assert primed.status_code == 202, primed.text  # 真的排入 outbox → verify-send:acct:{email} 蓋章

    # 此刻才讓該 Email 變成「不可用」；pending 列先清掉，避免與待測狀態並存
    await db.execute(delete(DpPendingRegistration).where(DpPendingRegistration.email == email))
    if state == "registered":
        await _verified_user(db, user_id=f"u_{state}", email=email)
    else:
        await _admin_invite(db, email=email)
    await db.commit()

    blocked = await client.post("/api/register", json=_payload(email))

    if state == "registered":
        # #86 不變：終局狀態優先於冷卻回應，否則使用者白等一輪倒數。
        assert blocked.status_code == 409, "回 429 代表可用性判定被移到冷卻之後（#86 的回歸）"
        assert blocked.json()["error_code"] == "DP_USER_001"
    else:
        # ⚠️ #345 之後受邀者**不再有終局狀態**，所以不適用 #86 的優先權——它必須與
        # 「全新 Email 在同一情境」給出相同答案，而那是 429（自己剛寄過、probe 章還在）。
        #
        # 這裡刻意**不是** 202：若讓受邀者在此回 202，同一 IP 連打兩次就會變成新的 oracle
        # （受邀 -> 202, 202；全新 -> 202, 429）。本條釘住的正是「別為了讓受邀者好過而岔開」。
        assert blocked.status_code == 429, "受邀者在自己的冷卻內須與全新 Email 同樣回 429"


class TestCrossEndpointClosed:
    """**已關閉**（#345）：login × register 交叉比對不再切得出「未逾期邀請」。

    ⚠️ 本 class 的前身是 `TestCrossEndpointResidual`——它正面**釘住**該殘留，理由是
    「被測試釘住的已知殘留」與「被誤以為已關閉的洞」是兩件事。#345 根治之後改寫為驗證
    已關閉（而非刪除）：殘留消失了，但**它不該復活**這件事需要有守衛。

    > 原 class 的註解寫「那時請連同這段說明一起刪除」。#345 的驗收條件改訂為「轉為驗證
    > 已關閉、連同說明一起改寫」——刪掉會讓這條回歸從此沒有測試，而它正是最容易在
    > 「為了 UX 把某一格的回應岔開」時被無聲打開的。

    `DP_AUTH_008` 仍與 `DP_AUTH_007` 可分辨——**刻意保留**（#208 AC 2），見下方測試。
    """

    async def test_三種_email_的交叉比對不再切得出受邀者(self, client, db) -> None:
        """(login error_code, register status) 的三格對照：受邀者已與「不存在」同格。

        對照表式而非逐條斷言——重點是**哪些格子彼此相同**，分開驗三條會全綠卻驗不到
        「它們之間的關係」，而關係才是列舉面的本體。
        """
        await _verified_user(db, user_id="u_x_reg", email="x-registered@edms.local")
        await _admin_invite(db, email="x-invited@edms.local")
        await db.commit()

        async def probe(email: str) -> tuple[str | None, int]:
            login = await client.post("/api/login", json={"email": email, "password": "AnyPwd1234"})
            register = await client.post("/api/register", json=_payload(email))
            return login.json().get("error_code"), register.status_code

        registered = await probe("x-registered@edms.local")
        invited = await probe("x-invited@edms.local")
        absent = await probe("x-absent@edms.local")

        assert invited == absent, "『已受邀』與『不存在』必須落在同一格——這就是 #345 關掉的洞"
        assert registered == ("DP_AUTH_008", 409), "已註冊仍可探測：#208 AC 2 明訂保留"
        assert registered != invited, (
            "正向錨點：三格若全部相同，代表 409 整個消失了——那會連『已註冊』的既有 UX 一起拆掉"
        )


async def test_他人冷卻中的回應與全新_email_相同(client, db, as_ip) -> None:
    """#346：`register` 的 429 曾是「該 Email 有未逾期自助註冊待驗證列」的 oracle。

    `verify-send:acct:{email}` 由**受害者自己**註冊時蓋上（真的寄出才蓋，#213）。攻擊者
    隨後打 register 得 429 ⇒ 推得「600 秒內有人對此 Email 成功寄出驗證信」。改為靜默 202。
    """
    victim = "cooldown-victim@edms.local"

    as_ip("198.51.100.7")  # 受害者自己註冊 -> 真的寄出 -> 蓋 acct 章
    first = await client.post("/api/register", json=_payload(victim))
    assert first.status_code == 202, first.text

    as_ip("203.0.113.9")  # 攻擊者，不同 IP：acct 章在、但 probe 章是乾淨的
    probe = await client.post("/api/register", json=_payload(victim))
    fresh = await client.post("/api/register", json=_payload("cooldown-fresh@edms.local"))

    assert probe.status_code == 202, "他人的冷卻對探測者必須是靜默的"
    assert probe.json() == fresh.json(), "回應需與全新 Email 逐欄位相同"


async def test_他人冷卻中不覆蓋既有_pending(client, db, as_ip) -> None:
    """#346 的另一半：靜默**不得**實作成「照常覆蓋」。

    ⚠️ 照常覆蓋等於讓任何匿名者每 600 秒作廢一次受害者的驗證連結——那會重開 #212。
    """
    victim = "cooldown-intact@edms.local"
    as_ip("198.51.100.7")
    assert (await client.post("/api/register", json=_payload(victim))).status_code == 202
    before = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == victim))).scalar_one()
    token_before, expires_before = before.token_hash, before.expires_date

    as_ip("203.0.113.9")  # 攻擊者
    await client.post("/api/register", json=_payload(victim))

    after = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == victim))).scalar_one()
    assert after.token_hash == token_before, "受害者的驗證連結不得被作廢"
    assert after.expires_date == expires_before, "效期不得被延長或重設"


async def test_自己的冷卻仍明說_429(client, db, as_ip) -> None:
    """#346 AC 3：別人的冷卻對你是靜默的，**自己的**冷卻才明說——否則防狂發退化。

    ⚠️ 若成功路徑只蓋 `acct` 章而不蓋 `probe` 章，同一人重打會撞 acct 章 → 依新規則變成
    靜默 202 → 他以為信一直在寄、實際一封都沒有。本條釘住「成功時兩個章都要蓋」。
    """
    email = "self-cooldown@edms.local"
    as_ip("198.51.100.7")

    first = await client.post("/api/register", json=_payload(email))
    assert first.status_code == 202, first.text

    again = await client.post("/api/register", json=_payload(email))

    assert again.status_code == 429, "同一 IP x Email 重打應明說冷卻中，不得退化成靜默 202"


async def test_受邀列未被探測動到(client, db) -> None:
    """#125 的保護不得鬆動：被靜默的註冊不可覆蓋邀請列。

    ⚠️ #345 把回應從 409 改成 202 之後，本條**更重要**了——先前「擋不擋」由 409 本身昭告，
    現在外觀與成功註冊完全相同，**唯一能分辨有沒有被覆蓋的就是這條測試**。少了它，把
    判定改成放行也能讓上面幾條全綠，而那會讓任何匿名者抹掉管理者發出的邀請（#125）。
    """
    email = "intact@edms.local"
    await _admin_invite(db, email=email)
    await db.commit()
    original = hash_token(f"invite-{email}")
    expires_before = (
        await db.execute(select(DpPendingRegistration.expires_date).where(DpPendingRegistration.email == email))
    ).scalar_one()

    probed = await client.post("/api/register", json=_payload(email))
    assert probed.status_code == 202, "#345：改為靜默 202；#125 的保護改由『什麼都不寫』達成"

    row = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == email))).scalar_one()
    assert row.token_hash == original, "原邀請信連結必須仍然有效"
    assert row.kind == KIND_ADMIN_INVITE and row.user_name == "受邀者"
    assert row.expires_date == expires_before, "效期不得被延長（否則等於讓匿名者替邀請續命）"


async def test_自己冷卻內受邀與全新_email_同形(client, db, as_ip) -> None:
    """補完矩陣的最後一格（#345 + #346）。

    三種「我自己剛打過」的情境必須給出相同回應，否則同一 IP 連打兩次就是新的 oracle：

    | 第 1 次 | 第 2 次（同 IP）|
    |---|---|
    | 全新 -> 202（真的寄出）| 429 |
    | 受邀 -> 202（靜默）| **429** |

    ⚠️ 直覺會想讓受邀者第 2 次也回 202（「反正本來就沒寄」），但那正好把兩者分開。
    靜默路徑蓋 `probe` 章就是為了讓這一格對齊。
    """
    as_ip("198.51.100.42")
    await _admin_invite(db, email="pair-invited@edms.local")
    await db.commit()

    invited_1 = await client.post("/api/register", json=_payload("pair-invited@edms.local"))
    invited_2 = await client.post("/api/register", json=_payload("pair-invited@edms.local"))
    fresh_1 = await client.post("/api/register", json=_payload("pair-fresh@edms.local"))
    fresh_2 = await client.post("/api/register", json=_payload("pair-fresh@edms.local"))

    assert (invited_1.status_code, invited_2.status_code) == (202, 429)
    assert (fresh_1.status_code, fresh_2.status_code) == (202, 429)
    assert invited_1.json() == fresh_1.json(), "第 1 次的回應必須逐欄位相同"
