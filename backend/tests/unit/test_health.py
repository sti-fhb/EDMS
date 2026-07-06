"""骨架健康度單元測試。

不依賴真實 DB：只驗證 FastAPI app 能正常組裝、公開端點可回應、
例外處理器已註冊（未知路由回標準錯誤格式）。
"""

import httpx
import pytest
from httpx import ASGITransport

from main import app


@pytest.mark.unit
async def test_version_endpoint_ok():
    """/api/version 應回 200 並含 version 欄位（不需 DB）。"""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/version")
    assert resp.status_code == 200
    assert "version" in resp.json()


@pytest.mark.unit
async def test_client_info_endpoint_ok():
    """/api/client-info 應回 200 並含 ip / is_ipv6 欄位（不需 DB）。"""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/client-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "ip" in body
    assert "is_ipv6" in body


@pytest.mark.unit
async def test_unknown_route_returns_standard_error():
    """未知路由應由 http_exception_handler 轉為標準錯誤格式（error_code=HTTP_404）。"""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "HTTP_404"
