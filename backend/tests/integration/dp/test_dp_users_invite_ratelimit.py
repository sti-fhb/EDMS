"""#72 邀請端點加固——router 接線整合測試。

驗「接線」：建立 / 重寄邀請兩端點確實掛上**操作者維度**限流（超限 429）、
重寄另掛 **res_id 冷卻**（冷卻中 429 帶 retry_after）。
限流 / 冷卻邏輯本身的邊界（視窗刷新、剩餘秒計算）已由 tests/unit/test_core_rate_limit.py、
tests/unit/test_core_cooldown.py 覆蓋，此處只驗 dp-users 兩端點有無掛對。
"""

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.users import router as users_router
from app.dp.users.models import DpUser
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration


async def _seed_operator(db, user_id: str) -> None:
    """建立 ACTIVE 操作者——get_jwt_payload 每請求查 DP_USER，無此列則 401。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash="x",
            user_name="操作者",
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


class _FakeNotify:
    """假發信服務：吞掉 send_email，不寫 outbox、不連 SMTP。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def send_email(self, _db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients, "template_code": template_code})


@pytest.fixture(autouse=True)
def _reset_invite_guards():
    """隔離 module-level 限流 / 冷卻單例狀態，並以假發信取代真 NotifyService（避免寫 outbox / 連 SMTP）。"""
    orig_service = users_router._service
    orig_max = users_router._invite_limiter._max
    users_router._service = UsersService(notify=_FakeNotify())
    users_router._invite_limiter._hits.clear()
    users_router._invite_resend_cooldown._last.clear()
    yield
    users_router._service = orig_service
    users_router._invite_limiter._max = orig_max
    users_router._invite_limiter._hits.clear()
    users_router._invite_resend_cooldown._last.clear()


def _auth(user_id: str = "admin01") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def test_create_invite_over_limit_returns_429(client, db):
    """同一操作者建立邀請超過 INVITE_RATE_MAX → 429 COMMON_429（操作者維度限流）。"""
    await _seed_operator(db, "admin01")
    users_router._invite_limiter._max = 2
    headers = _auth()

    r1 = await client.post("/api/dp/users", json={"email": "inv1@edms.local", "user_name": "邀一"}, headers=headers)
    r2 = await client.post("/api/dp/users", json={"email": "inv2@edms.local", "user_name": "邀二"}, headers=headers)
    r3 = await client.post("/api/dp/users", json={"email": "inv3@edms.local", "user_name": "邀三"}, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r3.status_code == 429
    assert r3.json()["error_code"] == "COMMON_429"


async def test_create_invite_limit_is_per_operator(client, db):
    """限流以操作者維度分桶：A 打滿不影響 B。"""
    await _seed_operator(db, "opA")
    await _seed_operator(db, "opB")
    users_router._invite_limiter._max = 1

    a1 = await client.post("/api/dp/users", json={"email": "a1@edms.local", "user_name": "A1"}, headers=_auth("opA"))
    a2 = await client.post("/api/dp/users", json={"email": "a2@edms.local", "user_name": "A2"}, headers=_auth("opA"))
    b1 = await client.post("/api/dp/users", json={"email": "b1@edms.local", "user_name": "B1"}, headers=_auth("opB"))

    assert a1.status_code == 202
    assert a2.status_code == 429  # opA 超限
    assert b1.status_code == 202  # opB 獨立額度、不受 opA 影響


async def test_resend_within_cooldown_returns_429_with_retry_after(client, db):
    """同一邀請 res_id 於冷卻內重寄 → 429 帶 retry_after；首次重寄回 retry_after＝完整冷卻秒。"""
    await _seed_operator(db, "admin01")
    headers = _auth()
    # 先建立一筆邀請，取得 res_id
    created = await client.post("/api/dp/users", json={"email": "res@edms.local", "user_name": "重寄"}, headers=headers)
    assert created.status_code == 202
    pending = await AuthRepository().get_pending_by_email(db, "res@edms.local")
    res_id = pending.res_id

    first = await client.post(f"/api/dp/users/invites/{res_id}/resend", headers=headers)
    second = await client.post(f"/api/dp/users/invites/{res_id}/resend", headers=headers)

    assert first.status_code == 202
    assert first.json()["retry_after"] == 60  # 預設 INVITE_RESEND_COOLDOWN_SEC
    assert second.status_code == 429
    body = second.json()
    assert body["error_code"] == "COMMON_429"
    assert 1 <= body["retry_after"] <= 60
