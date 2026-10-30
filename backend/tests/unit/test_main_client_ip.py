"""client_ip_middleware 端到端解析測試（#23）。

驗證「偽造 XFF 無法改變 middleware 判定的 client IP」——稽核日誌
（AuditLogService）與速率限制（rate_limit_by_ip）皆讀同一個 contextvar，
故此處驗到的值即兩者共用的來源。

探針：測試內自建臨時 app，掛上 main.py **同一個** `client_ip_middleware`，
並以一支只存在於測試的路由回吐 contextvar。正式 app 不提供任何回吐判定值的
端點（#199：公開回顯端點可被用來盲測 `TRUSTED_PROXY_COUNT`，已移除）；
middleware 確實掛在正式 app 上這件事，另由 `test_middleware_registered_on_main_app` 保證。
"""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.core.config import settings
from app.core.request_context import get_client_ip
from main import app, client_ip_middleware

pytestmark = pytest.mark.unit

_PEER = "198.51.100.9"

_probe_app = FastAPI()
_probe_app.middleware("http")(client_ip_middleware)


@_probe_app.get("/probe")
async def _probe() -> dict[str, str | None]:
    return {"ip": get_client_ip()}


async def _get_client_ip(headers: dict[str, str] | list[tuple[str, str]] | None = None) -> str | None:
    transport = ASGITransport(app=_probe_app, client=(_PEER, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe", headers=headers or {})
    assert resp.status_code == 200
    return resp.json()["ip"]


def test_middleware_registered_on_main_app():
    """探針 app 驗的是同一個函式；此條確保它確實掛在正式 app 上，未被拔除。"""
    assert any(m.kwargs.get("dispatch") is client_ip_middleware for m in app.user_middleware)


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


async def test_multiple_forwarded_for_headers_are_joined(monkeypatch):
    """攻擊者另送一個 X-Forwarded-For header 時，仍以代理追加的段落為準。

    依 RFC 7230 §3.2.2，同名 header 多次出現等同以逗號依序併為單一清單；
    若只取第一個出現值（headers.get），攻擊者即可讓代理追加的段落被忽略。
    """
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    headers = [("X-Forwarded-For", "9.9.9.9"), ("X-Forwarded-For", "203.0.113.7")]
    assert await _get_client_ip(headers) == "203.0.113.7"
