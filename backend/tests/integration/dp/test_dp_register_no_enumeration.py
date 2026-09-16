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

## 收斂到什麼程度（與**沒有**收斂到的程度）

**單看本端點**，合併後只可分辨 `{已註冊 或 已受邀}` 與 `{其他}`（前者 409、後者 202），
因為「已註冊」本來就是公開可探測的（同 login 的 `DP_AUTH_008`，#208 AC 2 明訂保留）。

⚠️ **但「誰被邀請了」並未真正關閉，探測成本只是從 1 個請求變成 2 個。** 交叉比對即可切開：

```
① POST /api/login（密碼任意）→ DP_AUTH_007  ⇒ 無未刪除的 DP_USER 列
② POST /api/register          → DP_USER_001 ⇒ DP_USER 列存在（含軟刪）或有未逾期邀請
①∩② = {未逾期 ADMIN_INVITE} ∪ {軟刪除的 DP_USER}
```

第二項在本專案是**空集合**（系統無刪除使用者功能，`DP_USER.DELETED` 從不被設定；
`email_exists` 含軟刪、`get_by_email` 排除軟刪，本該構成雜訊的差集實際上為空），
於是交集就是邀請名單本身。

`TestCrossEndpointResidual` 把這個殘留**釘住**——不是因為它可接受，而是因為「被測試釘住的
已知殘留」與「被誤以為已關閉的洞」是兩件事。根治要讓未逾期邀請離開 409 集合，會動到
`spec_us2` AC 6a 的對外行為，**追蹤於 #345**。
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


def _payload(email: str) -> dict:
    return {"email": email, "user_name": "探測者"}


def _signature(resp) -> tuple[int, str | None, str | None]:
    body = resp.json()
    return (resp.status_code, body.get("error_code"), body.get("error_message"))


async def test_已受邀與已註冊的註冊回應完全一致(client, db) -> None:
    """核心：兩者的 status / error_code / error_message 三者皆同。

    分開斷言「各自回 409」也會全綠卻驗不到重點——必須在同一條裡比較，否則任何一方的碼或
    訊息日後被改動，兩條各自的斷言都還會過。
    """
    await _verified_user(db, user_id="u_reg_enum", email="registered@edms.local")
    await _admin_invite(db, email="invited@edms.local")
    await db.commit()

    registered = await client.post("/api/register", json=_payload("registered@edms.local"))
    invited = await client.post("/api/register", json=_payload("invited@edms.local"))

    assert registered.status_code == 409, registered.text
    assert _signature(registered) == _signature(invited), "『已受邀』不得與『已註冊』區分開來"
    assert registered.json()["error_code"] == "DP_USER_001"


async def test_統一訊息同時鋪出登入與收信兩條路(client, db) -> None:
    """受邀者沒有 `DP_USER` 列，忘記密碼對他是防列舉的靜默 no-op。

    舊的 `_EMAIL_TAKEN_MSG` 只寫「請直接登入或使用忘記密碼」，受邀者照著做會走進死路——
    所以合併之後訊息**必須**同時提到「收到的啟用 / 驗證信」這條路。
    """
    await _admin_invite(db, email="guide@edms.local")
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

    assert blocked.status_code == 409, "終局狀態應優先於冷卻回應（#86）——回 429 代表檢核被移到冷卻之後"
    assert blocked.json()["error_code"] == "DP_USER_001"


class TestCrossEndpointResidual:
    """**已知未關閉**：login × register 交叉比對仍可取出「未逾期邀請」。

    釘住它的理由與 `test_dp_login_no_enumeration.py::TestVerifiedAccountUnchanged` 相同——
    讓殘留成為「被寫下來且有守衛的事實」。若日後根治（讓未逾期邀請離開 409 集合），本 class
    會轉紅，那時請連同這段說明一起刪除，而不是改斷言（#345 的驗收條件已寫明此事）。

    另有一條互補的殘留——`/api/register` 的 429 洩漏「該 Email 有未逾期的自助註冊待驗證列」
    （#213 引入，走共用冷卻 key）——追蹤於 **#346**，本 class 不涵蓋它。
    """

    async def test_交叉比對仍可切出未逾期邀請(self, client, db) -> None:
        """三種 Email 走同一組兩個請求，只有「已受邀」落在 (007, 409) 這一格。

        這條測試的價值不在「驗證正確行為」，而在**量化殘留的精確度**：若日後有人以為
        #208 已經關掉邀請列舉而據此做決策（例如放寬邀請信的內容），這裡寫著它沒有。
        """
        await _verified_user(db, user_id="u_x_reg", email="x-registered@edms.local")
        await _admin_invite(db, email="x-invited@edms.local")
        await db.commit()

        async def probe(email: str) -> tuple[str | None, int]:
            login = await client.post("/api/login", json={"email": email, "password": "AnyPwd1234"})
            register = await client.post("/api/register", json=_payload(email))
            return login.json().get("error_code"), register.status_code

        assert await probe("x-registered@edms.local") == ("DP_AUTH_008", 409)
        assert await probe("x-invited@edms.local") == ("DP_AUTH_007", 409), (
            "（007, 409）這一格目前唯一對應「未逾期 ADMIN_INVITE」——這就是尚未關閉的殘留"
        )
        assert await probe("x-absent@edms.local") == ("DP_AUTH_007", 202)


async def test_受邀列未被探測動到(client, db) -> None:
    """#125 的保護不得因合併而鬆動：被擋下的註冊不可覆蓋邀請列。

    合併改的是「回什麼」，不是「擋不擋」。少了這條，把檢核改成放行也能讓上面三條全綠。
    """
    email = "intact@edms.local"
    await _admin_invite(db, email=email)
    await db.commit()
    original = hash_token(f"invite-{email}")

    blocked = await client.post("/api/register", json=_payload(email))
    assert blocked.status_code == 409

    row = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == email))).scalar_one()
    assert row.token_hash == original, "原邀請信連結必須仍然有效"
    assert row.kind == KIND_ADMIN_INVITE and row.user_name == "受邀者"
