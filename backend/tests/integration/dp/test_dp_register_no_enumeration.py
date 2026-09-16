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

## 收斂到什麼程度

合併後仍可分辨 `{已註冊 或 已受邀}` 與 `{其他}`（前者 409、後者 202），因為「已註冊」本來
就是公開可探測的（同 login 的 `DP_AUTH_008`，#208 AC 2 明訂保留）。**但「誰被邀請了」已無法
單獨判定**——那正是本次要關掉的那一格。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

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


async def test_冷卻武裝時兩者仍不可區分(client, db) -> None:
    """位置差也是 oracle：若一個擋在冷卻前、一個擋在冷卻後，武裝時會變成 409 vs 429。

    `assert_email_available` 把兩個檢核合併在冷卻 check **之前**就是為了這個；本條確認該性質
    不只存在於程式結構，也真的成立於端點行為。
    """
    await _verified_user(db, user_id="u_cool_enum", email="cool-registered@edms.local")
    await _admin_invite(db, email="cool-invited@edms.local")
    await db.commit()

    # 以一次成功註冊武裝冷卻（router 的 key 為 Email 維度，但冷卻器是同一個單例）
    primed = await client.post("/api/register", json=_payload("fresh-cool@edms.local"))
    assert primed.status_code == 202, primed.text

    registered = await client.post("/api/register", json=_payload("cool-registered@edms.local"))
    invited = await client.post("/api/register", json=_payload("cool-invited@edms.local"))

    assert _signature(registered) == _signature(invited)
    assert registered.status_code == 409, "終局狀態應優先於冷卻回應（#86），且兩者一致"


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
