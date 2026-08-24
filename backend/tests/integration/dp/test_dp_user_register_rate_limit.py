"""註冊端點獨立限流門檻（#44）。

註冊是**匿名寫入型**端點，原本沿用登入的 10 次/分（600 帳號/小時/IP）偏寬鬆。
收緊為 REGISTER_RATE_MAX＝5 次/分，且不再與登入共用常數——日後調登入門檻不會
連帶放寬註冊。

限流器為 module-level 單例，本檔測試會刻意打滿配額，故 setup 與 teardown 都清空狀態，
避免污染其他測試（或被其他測試殘留的計數影響）。
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


def test_register_threshold_is_independent_and_stricter_than_login():
    """門檻自成常數且嚴於登入——避免日後調登入門檻連帶放寬匿名建帳號。"""
    assert REGISTER_RATE_MAX == 5
    assert REGISTER_RATE_MAX < LOGIN_RATE_MAX


async def test_register_over_ip_threshold_returns_429(client):
    """同 IP 第 6 次註冊（各用不同 Email 避開帳號維度與冷卻）→ 429 COMMON_429。"""
    for i in range(REGISTER_RATE_MAX):
        r = await client.post("/api/register", json=_payload(f"rate-{i}@edms.local"))
        assert r.status_code == 202, f"第 {i + 1} 次應放行，實際 {r.status_code}"

    over = await client.post("/api/register", json=_payload("rate-over@edms.local"))
    assert over.status_code == 429
    assert over.json()["error_code"] == "COMMON_429"
