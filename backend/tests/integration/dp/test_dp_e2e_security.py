"""T053 安全性驗收端到端整合測試（SC-004 + 安全防護）。

聚焦跨概念安全姿態（限流 / token / 密碼策略單點行為由 test_core_rate_limit / _forgot /
_auth 覆蓋）：
- **登入端點限流**：同 IP 逾門檻 → 429（驗限流器確實接到 /api/login，非僅單元）。
- **防帳號列舉一致**：忘記密碼對「存在 / 不存在」帳號回應一致、不洩漏帳號是否存在。
- **登入不洩漏待驗證列**：登入對「不存在 / 未驗證 / 已邀請」回同一碼同一句（#208）；
  與「密碼錯」的 `DP_AUTH_008` 之差異為 #208 AC 2 明訂保留。四種狀態的完整比對與
  稽核可區分性見 `test_dp_login_no_enumeration.py`，此處只留跨概念的姿態檢查。
"""

from datetime import timedelta

import pytest

from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.schemas import SendResult
from app.dp.user.forgot_service import ForgotPasswordService
from app.dp.user.models import DpPendingRegistration
from app.dp.user.router import _login_limiter
from app.dp.user.service import AuthService
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"


class _NotifyStub:
    def __init__(self):
        self.calls: list[dict] = []

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients})
        return SendResult(queued_count=len(recipients), skipped_reason=None)


@pytest.fixture
def reset_login_limiter():
    """清空登入限流器行程內狀態，隔離其他測試對同 IP 桶的污染。"""
    _login_limiter._hits.clear()
    yield
    _login_limiter._hits.clear()


async def _make_user(db, *, user_id, email, status="ACTIVE"):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash=hash_password(_PWD),
            user_name="安測",
            status=status,
            login_fail_count=0,
            pwd_changed_date=now - timedelta(days=1),
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


async def _seed_pending(db, *, email):
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token(generate_reset_token()),
            email=email,
            user_name="待驗證",
            pwd_hash=hash_password(_PWD),
            kind="SELF_REGISTER",
            expires_date=now + timedelta(minutes=30),
            created_user="SYSTEM",
            created_date=now,
        )
    )
    await db.flush()


async def test_login_rate_limited_after_threshold(client, reset_login_limiter):
    """同 IP 連續登入逾門檻（10/分）→ 第 11 次 429（限流器已接到 /api/login）。"""
    body = {"email": "nobody@edms.local", "password": "whatever1"}
    # 前 10 次：非 429（帳號不存在 → 401），不觸發限流
    for _ in range(10):
        r = await client.post("/api/login", json=body)
        assert r.status_code != 429
    # 第 11 次：同 IP 桶超限 → 429
    r = await client.post("/api/login", json=body)
    assert r.status_code == 429
    assert r.json()["error_code"] == "COMMON_429"


async def test_forgot_password_does_not_reveal_account_existence(db):
    """忘記密碼對存在 / 不存在帳號皆回 None（不拋、不洩漏）；僅存在者實際排信（SC-003 防列舉）。"""
    await _make_user(db, user_id="real", email="real@edms.local")
    notify_existing = _NotifyStub()
    notify_absent = _NotifyStub()

    # 存在帳號：回 None、實際寄信
    r1 = await ForgotPasswordService(notify=notify_existing).request(db, email="real@edms.local")
    # 不存在帳號：同樣回 None、靜默不寄（回應不因帳號是否存在而異）
    r2 = await ForgotPasswordService(notify=notify_absent).request(db, email="ghost@edms.local")

    assert r1 is None and r2 is None
    assert len(notify_existing.calls) == 1  # 存在 → 寄
    assert notify_absent.calls == []  # 不存在 → 不寄，但對外回應一致


async def test_login_does_not_reveal_pending_registration(db):
    """登入對「不存在」與「未驗證」回完全相同的回應（#208）。

    這條原本斷言三者相異，理由是 spec_us1 Clarification 把分流訂為引導式 UX。#208 推翻了
    該判斷：未驗證與已邀請的專屬回應讓匿名者密碼隨便填就能問出「誰被邀請了」，而引導可
    由一句涵蓋全部出路的中性訊息達成，不需靠「只對這類人顯示」。

    與忘記密碼（上一條）現在是同一種姿態——兩個端點對同一份資料的保護標準終於一致。
    """
    await _make_user(db, user_id="verified", email="verified@edms.local")
    await _seed_pending(db, email="pending@edms.local")

    with pytest.raises(AppError) as e_absent:
        await AuthService().login(db, email="unknown@edms.local", password=_PWD)
    with pytest.raises(AppError) as e_pending:
        await AuthService().login(db, email="pending@edms.local", password=_PWD)
    with pytest.raises(AppError) as e_wrong:
        await AuthService().login(db, email="verified@edms.local", password="wrong-pwd")

    def sig(exc):
        return (exc.value.status_code, exc.value.error_code, exc.value.detail)

    assert sig(e_absent) == sig(e_pending), "待驗證列的有無不得從回應看出"
    # DP_AUTH_008 仍相異：#208 AC 2 明訂保留（鎖定計數掛在該路徑上），非遺漏。
    assert e_wrong.value.error_code == "DP_AUTH_008"
