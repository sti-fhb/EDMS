"""SCAN_ACCESS_TTL_MIN 覆寫 login 之 access token 時效整合測試（真實 DB + 種子參數）。

renew 與 warning 之覆寫見 unit `test_dp_user_scan_access_ttl.py`；login 需真實帳號列才走得到核發。
"""

from datetime import timedelta

import pytest

from app.core.auth import decode_access_token
from app.core.config import settings
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.service import AuthService
from app.dp.users.models import DpUser
from app.services import ParamService

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"


async def _make_user(db, *, email: str) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=email.split("@")[0],
            email=email,
            pwd_hash=hash_password(_PWD),
            user_name="掃描測試",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now - timedelta(days=1),
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


def _token_lifetime_seconds(token: str) -> int:
    claims = decode_access_token(token)
    return int((claims.exp - claims.iat).total_seconds())


async def test_login_uses_dp_param_when_override_unset(db, monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定覆寫：login 之 TTL 與 expires_in 沿用 DP_PARAM JWT.ACCESS_TTL_MIN。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", None)
    await _make_user(db, email="scan_off@edms.local")
    param_ttl = await ParamService().get_int_param(db, "JWT", "ACCESS_TTL_MIN", -1)
    assert param_ttl > 0  # 種子參數存在，否則本測試驗不到「讀 DP_PARAM」

    result = await AuthService().login(db, email="scan_off@edms.local", password=_PWD)

    assert result.expires_in == param_ttl * 60
    assert _token_lifetime_seconds(result.access_token) == param_ttl * 60


async def test_login_uses_override_when_set(db, monkeypatch: pytest.MonkeyPatch) -> None:
    """設定覆寫：login 之 TTL 與 expires_in 採覆寫值（超出 DP_PARAM 上限 15 亦然）。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", 600)
    await _make_user(db, email="scan_on@edms.local")

    result = await AuthService().login(db, email="scan_on@edms.local", password=_PWD)

    assert result.expires_in == 600 * 60
    assert _token_lifetime_seconds(result.access_token) == 600 * 60
