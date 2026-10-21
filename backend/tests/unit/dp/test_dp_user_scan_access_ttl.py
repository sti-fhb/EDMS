"""SCAN_ACCESS_TTL_MIN 覆寫 access token 時效之單元測試（不連 DB，以替身 ParamService 取代）。

院內資安檢測（ZAP 自動化滲透測試）需單一 bearer token 連續掃描數小時，DP_PARAM
`JWT.ACCESS_TTL_MIN` 上限 15 分鐘不敷使用；由環境變數覆寫，未設定時行為不變。
login 之覆寫見 integration `test_dp_user_scan_access_ttl.py`（需真實帳號列）。
"""

import logging
from datetime import timedelta

import pytest

from app.core.auth import create_access_token, decode_access_token
from app.core.config import settings
from app.core.utils import utcnow
from app.dp.user import service as auth_service_module
from app.dp.user.service import AuthService, warn_if_scan_access_ttl_override

pytestmark = pytest.mark.unit

_PARAM_TTL_MIN = 7  # 刻意不同於預設 15，才分得出「讀了 DP_PARAM」與「退回預設」


class _FakeParamService:
    """替身 ParamService：回固定參數值，並記錄被查詢過的 (param_id, key)。"""

    def __init__(self) -> None:
        self.queried: list[tuple[str, str]] = []
        self._values = {("JWT", "ACCESS_TTL_MIN"): _PARAM_TTL_MIN, ("JWT", "RENEW_MAX_HOURS"): 8}

    async def get_int_param(self, db, param_id: str, key: str, default: int) -> int:
        self.queried.append((param_id, key))
        return self._values.get((param_id, key), default)


def _renew_payload():
    token = create_access_token(sub="u1", ttl_minutes=15, auth_time=utcnow() - timedelta(hours=1))
    return decode_access_token(token)


def _token_lifetime_seconds(token: str) -> int:
    claims = decode_access_token(token)
    return int((claims.exp - claims.iat).total_seconds())


async def test_renew_uses_dp_param_when_override_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定覆寫：換發 TTL 與 expires_in 沿用 DP_PARAM。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", None)
    params = _FakeParamService()
    result = await AuthService(params=params).renew(None, payload=_renew_payload())
    assert result.expires_in == _PARAM_TTL_MIN * 60
    assert _token_lifetime_seconds(result.access_token) == _PARAM_TTL_MIN * 60
    assert ("JWT", "ACCESS_TTL_MIN") in params.queried


async def test_renew_uses_override_and_skips_dp_param(monkeypatch: pytest.MonkeyPatch) -> None:
    """設定覆寫：換發 TTL 與 expires_in 採覆寫值，且不再讀 DP_PARAM 的 ACCESS_TTL_MIN。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", 600)
    params = _FakeParamService()
    result = await AuthService(params=params).renew(None, payload=_renew_payload())
    assert result.expires_in == 600 * 60
    assert _token_lifetime_seconds(result.access_token) == 600 * 60
    assert ("JWT", "ACCESS_TTL_MIN") not in params.queried
    # 換發上限照常檢核，覆寫只動 TTL
    assert ("JWT", "RENEW_MAX_HOURS") in params.queried


def test_warns_when_override_set(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """設定覆寫時留下 WARNING，維運看得出 token 時效被放寬。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", 600)
    with caplog.at_level(logging.WARNING, logger=auth_service_module.__name__):
        warn_if_scan_access_ttl_override()
    records = [r for r in caplog.records if r.name == auth_service_module.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "SCAN_ACCESS_TTL_MIN" in records[0].getMessage()
    assert "600" in records[0].getMessage()


def test_no_warning_when_override_unset(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """未設定覆寫時不留任何紀錄（行為完全不變）。"""
    monkeypatch.setattr(settings, "SCAN_ACCESS_TTL_MIN", None)
    with caplog.at_level(logging.DEBUG, logger=auth_service_module.__name__):
        warn_if_scan_access_ttl_override()
    assert not [r for r in caplog.records if r.name == auth_service_module.__name__]
