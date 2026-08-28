"""T053 安全性驗收端到端整合測試（SC-004 + 安全防護）。

聚焦跨概念安全姿態（限流 / token / 密碼策略單點行為由 test_core_rate_limit / _forgot /
_auth 覆蓋）：
- **登入端點限流**：同 IP 逾門檻 → 429（驗限流器確實接到 /api/login，非僅單元）。
- **防帳號列舉一致**：忘記密碼對「存在 / 不存在」帳號回應一致、不洩漏帳號是否存在。
- **登入訊息分流為刻意 UX**：登入對「不存在 / 未驗證 / 密碼錯」回不同碼——此為 spec_us1
  Clarification 明訂之引導式 UX，非列舉盲點；與忘記密碼的一致回應並存，各司其職。
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


async def test_login_branching_is_intentional_ux(db):
    """登入對三種情境回不同碼（spec_us1 明訂引導 UX，非列舉盲點）：不存在 / 未驗證 / 密碼錯。"""
    await _make_user(db, user_id="verified", email="verified@edms.local")
    await _seed_pending(db, email="pending@edms.local")

    # 不存在 → DP_AUTH_007
    with pytest.raises(AppError) as e_absent:
        await AuthService().login(db, email="unknown@edms.local", password=_PWD)
    # 未驗證（僅在待驗證表）→ DP_AUTH_010
    with pytest.raises(AppError) as e_pending:
        await AuthService().login(db, email="pending@edms.local", password=_PWD)
    # 已驗證、密碼錯 → DP_AUTH_008
    with pytest.raises(AppError) as e_wrong:
        await AuthService().login(db, email="verified@edms.local", password="wrong-pwd")

    codes = {e_absent.value.error_code, e_pending.value.error_code, e_wrong.value.error_code}
    assert codes == {"DP_AUTH_007", "DP_AUTH_010", "DP_AUTH_008"}  # 三者相異＝刻意分流
