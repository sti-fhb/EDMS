"""T048 鎖定與失效端到端整合測試（SC-002/005/006）。

串接跨 US 的鎖定 / 失效路徑：
- 連續錯密碼達門檻 → 自動鎖定 → 管理者解鎖（US4）→ 可再登入（SC-002）
- 停用帳號 → 登入即拒（SC-006；get_jwt_payload token 級停用閘另由 test_dp_auth_middleware 覆蓋）
- 活動換發逾單日上限 → 拒發，需重新登入（SC-005）

鎖定門檻 / 換發上限單點行為已有 per-feature 測試；此檔驗「鎖定→解鎖→再登入」「換發上限」之串接。
"""

from datetime import timedelta

import pytest

from app.core.auth import JwtPayload
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.service import AuthService
from app.dp.users.models import DpUser
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"
_OP = OperatorInfo(user_id="admin01")


async def _make_user(db, *, user_id="lk", email="lk@edms.local", status="ACTIVE"):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email,
        pwd_hash=hash_password(_PWD),
        user_name="鎖定測試",
        status=status,
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=1),
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


async def test_lock_then_admin_unlock_then_relogin(db):
    """連錯 5 次自動鎖定 → 正確密碼仍被鎖擋 → 管理者解鎖 → 可再登入（SC-002）。"""
    await _make_user(db)

    # 連續 5 次錯密碼：前幾次 DP_AUTH_008，達門檻後帳號鎖定
    for _ in range(5):
        with pytest.raises(AppError):
            await AuthService().login(db, email="lk@edms.local", password="wrong-pwd")

    # 鎖定中：即使正確密碼也被拒（DP_AUTH_005）
    with pytest.raises(AppError) as ei:
        await AuthService().login(db, email="lk@edms.local", password=_PWD)
    assert ei.value.error_code == "DP_AUTH_005"

    # 管理者解鎖（US4）→ 清鎖 + 歸零失敗計數
    await UsersService().unlock(db, user_id="lk", operator=_OP)

    # 解鎖後正確密碼可登入
    login = await AuthService().login(db, email="lk@edms.local", password=_PWD)
    assert login.must_change_pwd is False


async def test_disabled_account_login_rejected(db):
    """停用帳號登入即拒（DP_AUTH_004，SC-006）。"""
    await _make_user(db, user_id="dis", email="dis@edms.local")
    await UsersService().set_status(db, user_id="dis", action="disable", operator=_OP)

    with pytest.raises(AppError) as ei:
        await AuthService().login(db, email="dis@edms.local", password=_PWD)
    assert ei.value.error_code == "DP_AUTH_004"


async def test_renew_beyond_daily_cap_rejected(db):
    """換發逾單日上限（預設 8h）→ DP_AUTH_003，需重新登入（SC-005）。"""
    await _make_user(db, user_id="rn", email="rn@edms.local")
    now = utcnow()
    # auth_time 設在 9 小時前（逾 8h 上限）
    stale = JwtPayload(
        sub="rn",
        auth_time=now - timedelta(hours=9),
        iat=now - timedelta(hours=9),
        exp=now + timedelta(minutes=15),
    )
    with pytest.raises(AppError) as ei:
        await AuthService().renew(db, payload=stale)
    assert ei.value.error_code == "DP_AUTH_003"

    # 對照：auth_time 在 8h 內 → 換發成功
    fresh = JwtPayload(
        sub="rn",
        auth_time=now - timedelta(hours=1),
        iat=now - timedelta(hours=1),
        exp=now + timedelta(minutes=15),
    )
    token = await AuthService().renew(db, payload=fresh)
    assert token.access_token
