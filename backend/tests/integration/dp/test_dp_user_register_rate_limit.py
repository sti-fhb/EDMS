"""註冊端點限流門檻（#44）。

註冊與登入的門檻已解耦（`REGISTER_RATE_MAX`），且刻意**較登入寬鬆**：自助註冊是主要入口，
IP 維度無法區分「一個攻擊者狂送」與「一批使用者各送一次」，而內部平台的使用者常共用同一
對外 IP（教室 / 辦公室 NAT）。同一 Email 的重複註冊由 600 秒寄信冷卻把關，不靠本門檻。

限流器為 module-level 單例，本檔會刻意打滿配額，故 setup 與 teardown 都清空狀態。
出貨門檻為 30，逐次打 31 個 HTTP 請求成本過高（每次含約 209ms 的同步 bcrypt），
故行為測試以 monkeypatch 暫時縮小該實例的門檻——仍是真實端點、真實 dependency 接線。
"""

import pytest

from app.core.rate_limit import LOGIN_RATE_MAX, REGISTER_RATE_MAX
from app.dp.user import router as auth_router

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


@pytest.fixture(autouse=True)
def _reset_limits():
    auth_router._register_limiter._hits.clear()
    auth_router._verify_send_cooldown._last.clear()
    yield
    auth_router._register_limiter._hits.clear()
    auth_router._verify_send_cooldown._last.clear()


def _payload(email: str):
    return {"email": email, "user_name": "限流測試", "password": _GOOD_PWD, "confirm_password": _GOOD_PWD}


def test_register_threshold_is_decoupled_from_login():
    """門檻自成常數（與登入解耦），且刻意較登入寬鬆——理由見 core/rate_limit.py 的 #44 段。

    釘住「解耦」與「方向」兩件事：日後有人為排查登入問題調 LOGIN_RATE_MAX，不會連帶
    改動匿名建帳號；而若有人想把註冊收得比登入嚴，本測試會迫使他先回去讀那段理由。
    """
    assert REGISTER_RATE_MAX == 30
    assert REGISTER_RATE_MAX > LOGIN_RATE_MAX


async def test_register_over_ip_threshold_returns_429(client, monkeypatch):
    """超過 IP 維度門檻 → 429 COMMON_429（各用不同 Email，避開帳號維度與寄信冷卻）。"""
    monkeypatch.setattr(auth_router._register_limiter, "_max", 2)

    for i in range(2):
        r = await client.post("/api/register", json=_payload(f"rate-{i}@edms.local"))
        assert r.status_code == 202, f"第 {i + 1} 次應放行，實際 {r.status_code}"

    over = await client.post("/api/register", json=_payload("rate-over@edms.local"))
    assert over.status_code == 429
    body = over.json()
    assert body["error_code"] == "COMMON_429"
    # 限流版 429 不帶 retry_after（冷卻版才帶）——前端據此決定是否起倒數
    assert "retry_after" not in body
