"""#74 驗證信寄送冷卻——router 接線整合測試。

驗「接線」：register / resend 兩端點確實掛上共用冷卻（check 前置、record 後置）、
429 帶 retry_after、防列舉、共用額度、register 檢核失敗不誤觸冷卻。
冷卻邏輯本身的邊界（剩餘秒計算、視窗刷新等）已由 tests/unit/test_core_cooldown.py 覆蓋。
"""

import pytest

from app.dp.user import router as auth_router

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


@pytest.fixture(autouse=True)
def _reset_limits():
    """清除 module-level 冷卻器與相關限流器狀態，隔離跨測試污染（單例會殘留）。"""
    auth_router._verify_send_cooldown._last.clear()
    auth_router._register_limiter._hits.clear()
    auth_router._resend_limiter._hits.clear()
    yield


def _reg_payload(email: str, **over):
    base = {"email": email, "user_name": "冷卻測試", "password": _GOOD_PWD, "confirm_password": _GOOD_PWD}
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


async def test_register_validation_failure_does_not_start_cooldown(client):
    """註冊檢核失敗（密碼太弱 422）→ 未送信、不 record 冷卻；隨後對同 Email 仍可正常寄送。"""
    weak = await client.post(
        "/api/register", json=_reg_payload("cool-d@edms.local", password="abc", confirm_password="abc")
    )
    assert weak.status_code == 422

    # 因上一步未 record，冷卻未啟動 → resend 應放行（非 429）
    resend = await client.post("/api/resend-verification", json={"email": "cool-d@edms.local"})
    assert resend.status_code == 200
