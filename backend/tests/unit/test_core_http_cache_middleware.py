"""API 回應預設禁快取（#959）。

`DefaultNoStoreMiddleware` 只在回應**未自行設定** `Cache-Control` 時補上 `no-store`；
送檔／匯出端點自帶的 `NO_STORE_HEADERS` 必須原樣保留（送檔端點的涵蓋另由
`test_file_response_cache_coverage.py` 以 AST 釘住）。

探針 app 驗 middleware 本身的行為；正式 app 驗「確實掛上、且位置涵蓋上傳預檢的 401」。
"""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from httpx import ASGITransport

from app.core.http_cache import NO_STORE_HEADERS, DefaultNoStoreMiddleware
from main import app

pytestmark = pytest.mark.unit

_probe_app = FastAPI()
_probe_app.add_middleware(DefaultNoStoreMiddleware)


@_probe_app.get("/plain")
async def _plain() -> dict[str, str]:
    return {"ok": "1"}


@_probe_app.get("/own-header")
async def _own_header(tmp_file: str) -> FileResponse:
    return FileResponse(tmp_file, headers=NO_STORE_HEADERS)


@_probe_app.get("/stream")
async def _stream() -> StreamingResponse:
    async def _chunks():
        yield b"part1-"
        yield b"part2"

    return StreamingResponse(_chunks(), media_type="text/plain")


async def _get(target: FastAPI, method: str, path: str, **kwargs) -> httpx.Response:
    transport = ASGITransport(app=target)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


async def test_未自行設定快取指示的回應補上_no_store():
    resp = await _get(_probe_app, "GET", "/plain")
    assert resp.status_code == 200
    assert resp.headers.get_list("cache-control") == ["no-store"]


async def test_已自帶_NO_STORE_HEADERS_的送檔回應維持原值且不重複(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    resp = await _get(_probe_app, "GET", "/own-header", params={"tmp_file": str(f)})
    assert resp.status_code == 200
    assert resp.headers.get_list("cache-control") == [NO_STORE_HEADERS["Cache-Control"]]


async def test_串流回應補上_no_store_且_body_完整():
    resp = await _get(_probe_app, "GET", "/stream")
    assert resp.status_code == 200
    assert resp.content == b"part1-part2"
    assert resp.headers.get_list("cache-control") == ["no-store"]


async def test_正式_app_的_api_version_帶_no_store():
    """AC：`/api/version` 等未自行設定快取指示的 API 回應帶 `Cache-Control: no-store`。"""
    resp = await _get(app, "GET", "/api/version")
    assert resp.status_code == 200
    assert resp.headers.get_list("cache-control") == ["no-store"]


async def test_正式_app_上傳預檢的_401_也帶_no_store():
    """middleware 須掛在上傳預檢外層：未登入的寫入在預檢層就回 401，不進路由。"""
    resp = await _get(app, "PUT", "/api/dp/user/me", json={})
    assert resp.status_code == 401
    assert resp.headers.get_list("cache-control") == ["no-store"]
