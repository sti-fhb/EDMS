"""client_ip_middleware 端到端解析測試（#23）。

經真實 app 打公開端點 /api/client-info（其值直接取自 contextvar），
驗證「偽造 XFF 無法改變 middleware 判定的 client IP」——稽核日誌
（AuditLogService）與速率限制（rate_limit_by_ip）皆讀同一個 contextvar，
故此處驗到的值即兩者共用的來源。
"""

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from main import app

pytestmark = pytest.mark.unit

_PEER = "198.51.100.9"


async def _get_client_ip(headers: dict[str, str] | None = None) -> str | None:
    transport = ASGITransport(app=app, client=(_PEER, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/client-info", headers=headers or {})
    assert resp.status_code == 200
    return resp.json()["ip"]


async def test_forged_forwarded_for_ignored_by_default(monkeypatch):
    """預設未設信任代理：偽造 XFF 無效，判定值為不可偽造的連線對端。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    assert await _get_client_ip({"X-Forwarded-For": "9.9.9.9"}) == _PEER


async def test_trusted_proxy_reads_forwarded_for(monkeypatch):
    """設定 1 台信任代理：採信該代理追加的最右段。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert await _get_client_ip({"X-Forwarded-For": "203.0.113.7"}) == "203.0.113.7"


async def test_forged_prefix_ignored_with_trusted_proxy(monkeypatch):
    """設定信任代理後，用戶端前置的偽造段仍無法改變判定結果（限流桶不被打散）。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert await _get_client_ip({"X-Forwarded-For": "9.9.9.9, 203.0.113.7"}) == "203.0.113.7"


async def test_setting_read_per_request(monkeypatch):
    """設定於每個 request 讀取（非 import 時綁定），部署調整後不需改碼即生效。"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    assert await _get_client_ip({"X-Forwarded-For": "203.0.113.7"}) == _PEER
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert await _get_client_ip({"X-Forwarded-For": "203.0.113.7"}) == "203.0.113.7"
