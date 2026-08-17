"""#72 / #111 邀請端點加固——router 接線整合測試。

驗「接線」：
- 建立邀請**不設操作者總量限流**（PO 決策）：同一操作者批次建立多筆不同 Email 皆放行。
- 重寄邀請掛「invite_id 維度」冷卻（冷卻中 429 帶 retry_after），防對同一受邀信箱反覆轟炸。
- 對**已逾期**待啟用邀請重複建立 → 走「重新邀請」並回 202（#111 AC2）；該路徑受「Email 維度」
  寄信冷卻約束，冷卻內回 429（#111 補洞：逾期後原本擋住重複建立的 409 已不再全擋）。
冷卻邏輯本身的邊界（剩餘秒計算、視窗刷新）已由 tests/unit/test_core_cooldown.py 覆蓋，
此處只驗 dp-users 端點有無掛對。
"""

from datetime import timedelta

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
    """隔離 module-level 冷卻單例狀態，並以假發信取代真 NotifyService（避免寫 outbox / 連 SMTP）。

    替身 service 仍注入 router 的 `_invite_send_cooldown` 單例，讓測試能觀察 / 清除建立端點的冷卻。
    """
    orig_service = users_router._service
    users_router._service = UsersService(notify=_FakeNotify(), invite_cooldown=users_router._invite_send_cooldown)
    users_router._invite_resend_cooldown._last.clear()
    users_router._invite_send_cooldown._last.clear()
    yield
    users_router._service = orig_service
    users_router._invite_resend_cooldown._last.clear()
    users_router._invite_send_cooldown._last.clear()


def _auth(user_id: str = "admin01") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def test_create_invite_not_rate_limited_for_batch(client, db):
    """建立邀請不設操作者總量限流：同一操作者批次建立多筆不同 Email 皆 202（PO 決策）。"""
    await _seed_operator(db, "admin01")
    headers = _auth()

    for i in range(15):  # 遠超過舊門檻（10）；驗證不再有 operator 總量天花板
        resp = await client.post(
            "/api/dp/users",
            json={"email": f"batch{i}@edms.local", "user_name": f"批次{i}"},
            headers=headers,
        )
        assert resp.status_code == 202, f"第 {i + 1} 筆應放行，實得 {resp.status_code}"


async def test_resend_within_cooldown_returns_429_with_retry_after(client, db):
    """同一邀請 invite_id 於冷卻內重寄 → 429 帶 retry_after；首次重寄回 retry_after＝完整冷卻秒（600）。"""
    await _seed_operator(db, "admin01")
    headers = _auth()
    # 先建立一筆邀請，取得 invite_id
    created = await client.post("/api/dp/users", json={"email": "res@edms.local", "user_name": "重寄"}, headers=headers)
    assert created.status_code == 202
    pending = await AuthRepository().get_pending_by_email(db, "res@edms.local")
    invite_id = pending.invite_id

    first = await client.post(f"/api/dp/users/invites/{invite_id}/resend", headers=headers)
    second = await client.post(f"/api/dp/users/invites/{invite_id}/resend", headers=headers)

    assert first.status_code == 202
    assert first.json()["retry_after"] == 600  # 預設 INVITE_RESEND_COOLDOWN_SEC
    assert second.status_code == 429
    body = second.json()
    assert body["error_code"] == "COMMON_429"
    assert 1 <= body["retry_after"] <= 600


async def test_resend_cooldown_is_per_invite(client, db):
    """冷卻以 invite_id 分桶：一筆冷卻中不影響對「另一筆邀請」重寄（批次重寄不同人不被擋）。"""
    await _seed_operator(db, "admin01")
    headers = _auth()
    for email in ("inv-a@edms.local", "inv-b@edms.local"):
        r = await client.post("/api/dp/users", json={"email": email, "user_name": "X"}, headers=headers)
        assert r.status_code == 202
    repo = AuthRepository()
    res_a = (await repo.get_pending_by_email(db, "inv-a@edms.local")).invite_id
    res_b = (await repo.get_pending_by_email(db, "inv-b@edms.local")).invite_id

    # A 重寄兩次 → 第二次冷卻 429；B 首次重寄仍 202（獨立桶）
    assert (await client.post(f"/api/dp/users/invites/{res_a}/resend", headers=headers)).status_code == 202
    assert (await client.post(f"/api/dp/users/invites/{res_a}/resend", headers=headers)).status_code == 429
    assert (await client.post(f"/api/dp/users/invites/{res_b}/resend", headers=headers)).status_code == 202


# ---- #111 逾期待啟用邀請 → 重新邀請 ----


async def _expire_invite(db, email: str) -> None:
    """把某 Email 的待啟用邀請效期改為過去（模擬邀請連結逾期）。"""
    pending = await AuthRepository().get_pending_by_email(db, email)
    pending.expires_date = utcnow() - timedelta(minutes=1)
    await db.flush()


async def test_create_on_expired_pending_reinvites_with_202(client, db):
    """已逾期待啟用邀請重複建立 → 走重新邀請並回 **202**（#111 AC2：等同 resend 效果）。"""
    await _seed_operator(db, "admin01")
    headers = _auth()
    body = {"email": "exp@edms.local", "user_name": "初"}
    assert (await client.post("/api/dp/users", json=body, headers=headers)).status_code == 202
    await _expire_invite(db, "exp@edms.local")
    # 邀請逾期意味「距上次寄出已過一個完整效期（預設 30 分 > 冷卻 10 分）」，故清狀態模擬時間經過
    users_router._invite_send_cooldown._last.clear()

    again = await client.post("/api/dp/users", json={"email": "exp@edms.local", "user_name": "再"}, headers=headers)

    assert again.status_code == 202


async def test_reinvite_within_send_cooldown_returns_429(client, db):
    """重新邀請受「Email 維度」寄信冷卻約束（#111）：冷卻內 → 429 COMMON_429。

    效期被調短到冷卻以下（TTL 誤設）時，此冷卻是唯一阻止對同一信箱反覆寄信的防線。
    """
    await _seed_operator(db, "admin01")
    headers = _auth()
    body = {"email": "bomb@edms.local", "user_name": "初"}
    assert (await client.post("/api/dp/users", json=body, headers=headers)).status_code == 202
    await _expire_invite(db, "bomb@edms.local")

    again = await client.post("/api/dp/users", json={"email": "bomb@edms.local", "user_name": "再"}, headers=headers)

    assert again.status_code == 429
    assert again.json()["error_code"] == "COMMON_429"
