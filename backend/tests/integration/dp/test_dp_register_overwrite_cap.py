"""同一 Email 每日重建待驗證列的次數上限（#234）。

## 這張 issue 在修什麼

`/api/register` 每次覆蓋都重設 `expires_date = now + TTL`，而冷卻只有 600 秒 < TTL 1800 秒。
匿名者每 601 秒送一次即可讓那筆待驗證列**永遠不逾期**，於是：

- 管理者代建同一 Email **恆 409**（`create_user` 只對**逾期**的 `SELF_REGISTER` 列放行，#226）
- `SCHDP001.purge_expired_pending` 永遠觸及不到該列
- 受害者的 Email 被永久佔住，而該列在所有 UI 上都看不見

⚠️ `/api/resend-verification` 走的是**同一段**（`delete_pending_unless_active_invite` +
`create_pending_registration(expires_date=now + ttl)`），**一樣會刷新效期**。額度若只擋
register，攻擊者改打重寄就整個繞過——`test_重寄與註冊共用同一份額度` 即為此而設。

## 測試如何模擬「601 秒後」

清掉 module-level 的 `_verify_send_cooldown`（既有測試的慣用手法），但**不清**本次新增的
24 小時計數器——那正是受測對象：它必須跨越冷卻重置而繼續累積，否則攻擊者等冷卻過去就能重來。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.notify.schemas import SendResult
from app.dp.params.models import DpParamDetail
from app.dp.user import router as auth_router
from app.dp.user.models import DpPendingRegistration
from app.dp.users.schemas import UserCreate
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_CAP = 2  # 測試用的小上限（正式預設 5）；每多一次就多一輪完整的註冊 + 渲染


@pytest.fixture(autouse=True)
async def _reset_and_shrink_cap(db):
    """清掉單例狀態，並把每日上限調小以免每條測試都要跑 5 輪。

    ⚠️ **不清 `_overwrite_counter`** 以外的那一句是重點：本 fixture 之所以逐測試清它，
    是為了隔離測試間污染；而**單一測試之內**它必須跨冷卻重置存活，見本檔 docstring。
    """
    auth_router._verify_send_cooldown._last.clear()
    auth_router._register_limiter._hits.clear()
    auth_router._resend_limiter._hits.clear()
    auth_router._overwrite_counter._hits.clear()
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "LOGIN", DpParamDetail.param_key == "REGISTER_OVERWRITE_MAX_PER_DAY")
        .values(param_value=str(_CAP))
    )
    await db.commit()
    yield


@pytest.fixture
def as_ip(monkeypatch):
    """切換 router 眼中的 client IP（`_verify_send_probe_key` 用它分桶）。

    ⚠️ ASGI 測試傳輸沒有真實 peer 位址，且 `X-Forwarded-For` 預設**不受信**
    （`TRUSTED_PROXY_COUNT=0`，#23），送 header 不會改變 probe key。寫法比照
    `test_dp_register_no_enumeration.py` 的同名 fixture。
    """

    def _set(ip: str) -> None:
        monkeypatch.setattr(auth_router, "get_client_ip", lambda: ip)

    return _set


def _payload(email: str) -> dict:
    return {"email": email, "user_name": "額度測試"}


async def _register_later(client, email: str):
    """模擬「冷卻過後」再註冊一次：清冷卻章（不動 24h 計數器）後送出。"""
    auth_router._verify_send_cooldown._last.clear()
    return await client.post("/api/register", json=_payload(email))


async def _outbox(db, email: str) -> int:
    return await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.recipient == email))


async def _expires(db, email: str):
    return await db.scalar(
        select(DpPendingRegistration.expires_date).where(DpPendingRegistration.email == email)
    )


async def test_達上限後不再寄信(client, db) -> None:
    """超過上限的註冊不再寄出任何信——防的是對受害者信箱的持續轟炸。"""
    email = "cap-mail@edms.local"
    for _ in range(_CAP):
        assert (await _register_later(client, email)).status_code == 202
    assert await _outbox(db, email) == _CAP, "前提錨點：上限內每次都真的寄了，否則下面的『不再增加』恆真"

    for _ in range(3):
        assert (await _register_later(client, email)).status_code == 202
    assert await _outbox(db, email) == _CAP, "超過上限後不得再寄"


async def test_達上限後效期不再刷新(client, db) -> None:
    """**本 issue 的核心**：效期停止延後，該列因此終會逾期。

    效期不再被推遲 ⇒ 列會逾期 ⇒ `create_user` 對逾期的 `SELF_REGISTER` 列放行（#226）、
    `SCHDP001` 也清得到。下一條測試直接驗管理者那一端。
    """
    email = "cap-expiry@edms.local"
    for _ in range(_CAP):
        await _register_later(client, email)
    frozen = await _expires(db, email)
    assert frozen is not None

    for _ in range(3):
        await _register_later(client, email)
    assert await _expires(db, email) == frozen, "超過上限後 expires_date 不得再被推遲"


class _FakeNotify:
    """假發信：不寫 outbox，避免管理者代建的邀請信混進本檔的 outbox 斷言。"""

    async def send_email(self, _db, *, recipients, template_code, module, params, caller_module):
        return SendResult(queued_count=len(recipients), skipped_reason=None)


async def test_達上限且列逾期後_管理者代建成功(client, db) -> None:
    """AC 1：攻擊者無法再讓該 Email 永久進不來。

    直接把列改成已逾期＝模擬「時間走過 TTL」——而**能不能走到那一刻**正是本次修法的產出：
    修法前效期每 601 秒被推遲一次，這一刻永遠不會到來。

    走 service 而非 HTTP：比照 `test_dp_users_crud.py` 的既有慣例，驗的是代建的業務判定
    （`create_user` 對逾期 `SELF_REGISTER` 列的放行，#226），不是後台授權閘。
    """
    email = "cap-admin@edms.local"
    for _ in range(_CAP):
        await _register_later(client, email)
    frozen = await _expires(db, email)

    for _ in range(2):
        await _register_later(client, email)

    # 🔴 這條斷言是本測試與修法之間唯一的連結。少了它，下面手動把列改成逾期會讓測試
    # **拿掉修法照樣通過**——那時驗的只剩 #226 既有的「逾期列可被代建覆蓋」。
    # （2026-10-14 變異檢查 M4 實測：移除 over_cap 判定後本測試仍綠，故補入。）
    assert await _expires(db, email) == frozen, "額度用罄後效期仍被推遲 ⇒ 該列永不逾期，代建仍會 409"

    # 模擬時間走過 TTL。**能不能走到這一刻**正是修法的產出：修法前效期每 601 秒被推遲一次。
    await db.execute(
        update(DpPendingRegistration)
        .where(DpPendingRegistration.email == email)
        .values(expires_date=utcnow() - timedelta(minutes=1))
    )
    await db.commit()

    # 不拋即成功；修法前此處必拋 409 DP_USER_007（列永遠不逾期）
    await UsersService(notify=_FakeNotify()).create_user(
        db,
        data=UserCreate(email=email, user_name="管理者代建"),
        operator=OperatorInfo(user_id="admin01"),
    )


async def test_重寄與註冊共用同一份額度(client, db) -> None:
    """🔴 規劃階段才發現的漏算：`resend` 與 `register` 同形，一樣會刷新效期。

    額度若只擋 register，攻擊者改打 `/api/resend-verification` 即完全繞過，**修法等於沒做**。
    既有的 600 秒冷卻早已為同一理由共用額度（`FR-DP-US2-04b`）。
    """
    email = "cap-shared@edms.local"
    for _ in range(_CAP):
        await _register_later(client, email)
    before = await _outbox(db, email)
    assert before == _CAP

    auth_router._verify_send_cooldown._last.clear()
    resent = await client.post("/api/resend-verification", json={"email": email})
    assert resent.status_code == 200, "回應維持統一（防列舉），額度用罄不得從狀態碼看出來"
    assert await _outbox(db, email) == before, "重寄不得繞過每日額度"


async def test_達上限的回應與全新_email_完全相同(client, db) -> None:
    """額度用罄**不得**從回應看出來——否則變成可探測「這個 Email 近 24 小時被註冊過幾次」。

    這正是 #345 / #346 關掉的那一類 oracle，不能從另一個角度重新打開。
    """
    exhausted = "cap-shape-a@edms.local"
    for _ in range(_CAP + 1):
        await _register_later(client, exhausted)
    over = await _register_later(client, exhausted)

    fresh = await _register_later(client, "cap-shape-b@edms.local")

    assert over.status_code == fresh.status_code
    assert over.json() == fresh.json(), f"額度用罄 {over.json()} 與全新 {fresh.json()} 必須逐欄位相同"


async def test_靜默路徑不消耗受害者額度(client, db, as_ip) -> None:
    """探測行為不得吃掉受害者的額度（2026-10-14 變異檢查 M6 補入）。

    額度以 Email 為 key、分不出誰在送，所以「哪些請求計入」是唯一能保護受害者的地方：
    只有**真的重建列並寄信**那次才計入。靜默路徑（受邀者 / 他人冷卻中）既沒建列也沒寄信，
    計入它等於讓任何匿名者打幾下就把受害者的當日額度耗光。

    ⚠️ 本測試在修法當下是綠的，但變異檢查證明「把 try_record 移出 if sent」**不會讓任何
    測試變紅**——也就是這個性質原本零覆蓋。
    """
    email = "cap-silent@edms.local"
    as_ip("203.0.113.1")
    # 第 1 次真的寄出（額度 1/2），並蓋下 Email 章
    assert (await _register_later(client, email)).status_code == 202
    assert await _outbox(db, email) == 1

    # 🔴 必須**換 IP**才走得到靜默路徑。同一 IP 會先撞自己的 probe 冷卻而回 429，
    # 根本到不了 `others_cooling` 那條分支——2026-10-14 第一版就是這樣寫的，
    # 結果變異 M6 重跑仍全綠（測試根本沒執行到被注入的那行），斷言寫 `in (202, 429)`
    # 還把這件事藏了起來。
    # ⚠️ **每次都要換 IP**：靜默路徑自己也會蓋 probe 章，同一 IP 第二次就撞上自己的章而回 429，
    # 那時根本沒走到 `others_cooling` 分支。（2026-10-14 實際踩到：第一版用同一 IP 迴圈三次，
    # 看起來像實作壞了，其實是測試沒到達目標分支。）
    for ip in ("198.51.100.7", "198.51.100.8", "198.51.100.9"):
        as_ip(ip)
        silent = await client.post("/api/register", json=_payload(email))
        assert silent.status_code == 202, f"前提錨點：須走到靜默路徑，實得 {silent.status_code} {silent.text}"
    assert await _outbox(db, email) == 1, "前提錨點：靜默路徑確實沒寄信"

    as_ip("203.0.113.1")

    # 額度應仍剩 1 → 清冷卻後還能寄第 2 封
    assert (await _register_later(client, email)).status_code == 202
    assert await _outbox(db, email) == 2, "靜默路徑吃掉了額度：受害者少了一次機會"


async def test_上限值超界時被夾回合理範圍(client, db) -> None:
    """IT 直接改 DB 把上限設成界外時，讀取端夾回（2026-10-14 變異檢查 M7 補入）。

    `EDIT_SCOPE='HIDDEN'` ⇒ 唯一的修改路徑是直接下 SQL，而 `get_int_param` 對整數不設界。
    設成 0 會讓任何人都註冊不了；設成 99999 則靜默關掉整道防護。兩端都要夾。

    取下界測是因為它快：夾回 1 之後只准寄一封，兩次請求即可驗完。
    """
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "LOGIN", DpParamDetail.param_key == "REGISTER_OVERWRITE_MAX_PER_DAY")
        .values(param_value="0")
    )
    await db.commit()

    email = "cap-clamp@edms.local"
    assert (await _register_later(client, email)).status_code == 202
    assert await _outbox(db, email) == 1, "夾回下界 1 ⇒ 第一封仍須寄出（設 0 不得讓所有人都註冊不了）"

    await _register_later(client, email)
    assert await _outbox(db, email) == 1, "夾回下界 1 ⇒ 第二封不得寄出"
