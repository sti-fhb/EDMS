"""T047 認證鏈端到端整合測試（SC-001/003/004/005）。

串接跨 US 完整認證流程，驗證各 US 服務銜接無縫：
① 自助註冊（US2）→ 驗證（US2）→ 登入（US1）→ 活動換發（US1）→ 閒置逾時失效（US1）
   → 忘記密碼（US3）→ 重設（US3）→ 新密碼登入 / 舊密碼失效。
② 代建帳號 → 初始密碼首登（must_change）→ 強制變更密碼（US8）→ 正常登入。

明文 token 不落 DB（僅入信中連結），故以 NotifyStub 攔截 send_email 取回明文串接驗證 / 重設，
形成真正的端到端鏈（非各步 seed）。
"""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.auth import JwtPayload, create_access_token, decode_access_token
from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.profile_service import ProfileService
from app.dp.user.register_service import RegisterService
from app.dp.user.service import AuthService
from app.dp.user.verify_service import VerifyService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PWD1 = "Abcd1234"
_PWD2 = "Xyz98765!"


class _NotifyStub:
    """攔截 send_email 呼叫，保留 params 供取回信中連結的明文 token。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"template_code": template_code, "params": params})

    def last_token(self) -> str:
        """從最後一次 send_email 的任一 *_link 參數解析 token query。"""
        params = self.calls[-1]["params"]
        for value in params.values():
            if isinstance(value, str) and "token=" in value:
                return parse_qs(urlparse(value).query)["token"][0]
        raise AssertionError(f"send_email params 無帶 token 連結：{params}")


@pytest.fixture
def et_gate():
    """驗證步授予 ET 預設學員角色的 provisioning stub。"""
    granted: list[str] = []

    async def _grant(_db, user_id):
        granted.append(user_id)

    module_provisioning_gate.register("ET", _grant)
    yield granted
    module_provisioning_gate.unregister("ET")


async def test_self_service_auth_chain(db, et_gate):
    """自助註冊 → 驗證 → 登入 → 換發 → 閒置失效 → 忘記密碼 → 重設 → 新密碼登入。"""
    email = "chain@edms.local"
    notify = _NotifyStub()

    # ① 自助註冊（US2）：寫待驗證列 + 寄驗證信（攔截取 token）
    await RegisterService(notify=notify).register(
        db, email=email, user_name="鏈測試", password=_PWD1, confirm_password=_PWD1
    )
    verify_token = notify.last_token()

    # ② 驗證（US2）：建 DP_USER(ACTIVE) + 授 ET 學員
    await VerifyService().verify(db, token=verify_token)
    user = (await db.execute(_by_email(email))).scalar_one()
    assert user.status == "ACTIVE"
    assert et_gate == [user.user_id]  # SC-001 單一登入前置：預設角色已授

    # ③ 登入（US1）：核發 JWT，sub 可解碼（SC-001）
    login = await AuthService().login(db, email=email, password=_PWD1)
    assert login.must_change_pwd is False
    payload = decode_access_token(login.access_token)
    assert payload.sub == user.user_id

    # ④ 活動換發（US1）：沿用 auth_time 重簽新 token（SC-005 操作中靜默換發）
    renewed = await AuthService().renew(db, payload=payload)
    assert decode_access_token(renewed.access_token).sub == user.user_id

    # ⑤ 閒置逾時失效（US1，SC-005）：TTL 過期的 token 一律 DP_AUTH_002 拒
    expired = create_access_token(sub=user.user_id, ttl_minutes=-1)
    with pytest.raises(AppError) as ei:
        decode_access_token(expired)
    assert ei.value.error_code == "DP_AUTH_002"

    # ⑥ 忘記密碼（US3）：寄重設信（攔截取 token）
    await ForgotPasswordService(notify=notify).request(db, email=email)
    reset_token = notify.last_token()

    # ⑦ 重設（US3，SC-003 一次性 token）：換新密碼
    await ResetPasswordService().reset(db, token=reset_token, new_password=_PWD2, confirm_password=_PWD2)

    # ⑧ 新密碼可登入、舊密碼失效（SC-004）
    relogin = await AuthService().login(db, email=email, password=_PWD2)
    assert relogin.must_change_pwd is False
    with pytest.raises(AppError) as ei2:
        await AuthService().login(db, email=email, password=_PWD1)
    assert ei2.value.error_code == "DP_AUTH_008"


async def test_admin_created_force_change_chain(db):
    """代建帳號 → 初始密碼首登（must_change）→ 強制變更 → 正常登入（must_change 已清）。"""
    now = utcnow()
    user = DpUser(
        user_id="invitee",
        email="invitee@edms.local",
        pwd_hash=hash_password(_PWD1),
        user_name="受邀者",
        status="ACTIVE",
        login_fail_count=0,
        must_change_pwd=True,
        pwd_changed_date=now - timedelta(days=1),
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()

    # 初始密碼首登 → must_change_pwd True（登入成功但需強制變更）
    first = await AuthService().login(db, email="invitee@edms.local", password=_PWD1)
    assert first.must_change_pwd is True

    # 強制變更密碼（US8）：驗舊 + 換新 → 清 must_change
    await ProfileService().change_password(
        db, user_id="invitee", old_password=_PWD1, new_password=_PWD2, confirm_password=_PWD2
    )

    # 變更後以新密碼登入 → 正常（must_change 已清）
    after = await AuthService().login(db, email="invitee@edms.local", password=_PWD2)
    assert after.must_change_pwd is False


def _by_email(email: str):
    from sqlalchemy import select

    return select(DpUser).where(DpUser.email == email)