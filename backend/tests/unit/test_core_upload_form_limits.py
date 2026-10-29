"""上傳端點的表單解析上限（#833 A2）。

FastAPI 以不帶參數的 `request.form()` 解析 multipart，Starlette 預設允許 1000 個各 1 MB 的
非檔案欄位整份留在記憶體。`LimitedFormRoute` 先以較嚴的上限解析一次，FastAPI 拿到的是快取。

本檔分三部分：
- route class 行為：以最小的 FastAPI app 直接驅動 ASGI，驗「超量擋下、合法放行、拒絕前讀完 body」
- 守門（真正的 app）：每支收檔案的端點實際送超量欄位，必須被擋——漏設 route class 的 router 會紅
- 守門（上限夠不夠）：由 OpenAPI 推算每支端點合法的最大欄位數與最長欄位，不可超過上限
"""

import asyncio
import json
from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, FastAPI, File, Form, UploadFile

from app.core.auth import create_access_token
from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.upload_form_limits import (
    UPLOAD_MAX_FIELDS,
    UPLOAD_MAX_FILES,
    UPLOAD_MAX_PART_SIZE,
    LimitedFormRoute,
)
from main import app as real_app

pytestmark = pytest.mark.unit

_BOUNDARY = "edmsboundary"


def _multipart(fields: list[tuple[str, str]], files: int = 0) -> bytes:
    parts = [
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n' for name, value in fields
    ]
    parts += [
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="f{i}.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n%PDF\r\n"
        for i in range(files)
    ]
    return ("".join(parts) + f"--{_BOUNDARY}--\r\n").encode()


_CT = {"content-type": f"multipart/form-data; boundary={_BOUNDARY}"}


# ── route class 行為 ─────────────────────────────────────────────────


def _tiny_app() -> tuple[FastAPI, list[dict]]:
    received: list[dict] = []
    router = APIRouter(route_class=LimitedFormRoute)

    @router.post("/upload")
    async def upload(
        ids: Annotated[list[int], Form()] = [],  # noqa: B006
        note: Annotated[str, Form()] = "",
        file: Annotated[UploadFile | None, File()] = None,
    ):
        received.append({"ids": len(ids), "note": len(note), "file": file.filename if file else None})
        return {"ok": True}

    @router.post("/json")
    async def json_body(payload: dict):
        return payload

    app = FastAPI()
    app.state.errors = []

    @app.exception_handler(AppError)
    async def _app_error(_request, exc: AppError):
        from fastapi.responses import JSONResponse

        app.state.errors.append(exc)
        return JSONResponse(status_code=exc.status_code, content={"error_code": exc.error_code})

    app.include_router(router)
    return app, received


async def _post(app: FastAPI, path: str, content: bytes, headers: dict) -> httpx.Response:
    # ⚠️ 逾時是必要的：拒絕前若沒讀完 body，httpx 的 ASGITransport 會等不到回應而卡住，
    # 測試應該紅而不是掛到 CI 逾時
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        return await asyncio.wait_for(client.post(path, content=content, headers=headers), timeout=10)


async def test_合法的最大表單放行_路由拿到完整內容():
    """正向錨點：上限是照合法表單算的，合法的最大量必須通過，且路由拿到的值不缺。"""
    app, received = _tiny_app()
    fields = [("ids", str(i)) for i in range(UPLOAD_MAX_FIELDS - 1)] + [("note", "長" * 1000)]

    r = await _post(app, "/upload", _multipart(fields, files=UPLOAD_MAX_FILES), _CT)

    assert r.status_code == 200, r.text
    assert received == [{"ids": UPLOAD_MAX_FIELDS - 1, "note": 1000, "file": "f0.pdf"}]


@pytest.mark.parametrize(
    ("fields", "files"),
    [
        ([("ids", "1")] * (UPLOAD_MAX_FIELDS + 1), 0),
        ([("note", "x" * (UPLOAD_MAX_PART_SIZE + 1))], 0),
        ([], UPLOAD_MAX_FILES + 1),
    ],
    ids=["欄位過多", "單一欄位過大", "檔案過多"],
)
async def test_超量的表單在進路由前擋下_回_422(fields, files):
    app, received = _tiny_app()

    r = await _post(app, "/upload", _multipart(fields, files), _CT)

    assert r.status_code == 422
    assert r.json() == {"error_code": "COMMON_422"}
    assert received == [], "超量的表單不可交給路由"


async def test_每次拒絕都是新的例外物件():
    """共用同一個例外實例的話 traceback 會一路累積，持續送超量表單就能讓記憶體緩慢成長（code review）。"""
    app, _ = _tiny_app()
    body = _multipart([("ids", "1")] * (UPLOAD_MAX_FIELDS + 1))

    for _ in range(2):
        assert (await _post(app, "/upload", body, _CT)).status_code == 422

    first, second = app.state.errors
    assert first is not second


def test_最壞情況的記憶體有上限():
    """這才是上限要守的目的：非檔案欄位整份留在記憶體，最壞情況 = 欄位數 × 單欄上限。

    其他測試都以常數 +1 去送，常數被改大它們照樣通過（變異檢查實測：改回 Starlette 預設 1000 個
    全綠）。Starlette 預設是 1000 × 1 MB ≈ 1 GB；後端容器上限 2 GB（#830）。
    """
    assert UPLOAD_MAX_FIELDS * UPLOAD_MAX_PART_SIZE <= 16 * 1024 * 1024


async def test_JSON_路由不受影響():
    app, _ = _tiny_app()

    r = await _post(app, "/json", b'{"a": 1}', {"content-type": "application/json"})

    assert r.status_code == 200
    assert r.json() == {"a": 1}


class _Feeder:
    """把 body 切成多塊餵給 ASGI app，記錄讀與送的先後；body 讀完後再讀就是 bug（會卡到客戶端斷線）。"""

    def __init__(self, body: bytes, chunk: int, *, disconnect_after: int | None = None) -> None:
        self.chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)]
        self.events: list[str] = []
        self.sent: list[dict] = []
        self.read_after_end = False
        self._disconnect_after = disconnect_after

    async def receive(self) -> dict:
        index = self.events.count("receive")
        self.events.append("receive")
        if self._disconnect_after is not None and index >= self._disconnect_after:
            return {"type": "http.disconnect"}
        if index >= len(self.chunks):
            self.read_after_end = True
            await asyncio.sleep(3600)  # 模擬 uvicorn：body 讀完後 receive() 會等到客戶端斷線
        return {"type": "http.request", "body": self.chunks[index], "more_body": index < len(self.chunks) - 1}

    async def send(self, message: dict) -> None:
        self.events.append("send")
        self.sent.append(message)

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"] == "http.response.start")


async def _drive(app: FastAPI, feeder: _Feeder) -> None:
    """未處理的例外會從這裡拋出（Starlette 的 ServerErrorMiddleware 送完 500 後再往外拋）。"""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "root_path": "",
        "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in _CT.items()],
        "server": ("t", 80),
        "client": ("c", 1),
    }
    await asyncio.wait_for(app(scope, feeder.receive, feeder.send), timeout=10)


async def test_欄位過多時先讀完剩下的_body_才回應():
    """解析到一半就拒絕時 body 還沒讀完；直接回應的話，經過 nginx 的客戶端收到的回應會斷在半途
    （2026-10-29 實測，見 `upload_form_limits` 模組說明）。"""
    app, _ = _tiny_app()
    fields = [("ids", "1")] * (UPLOAD_MAX_FIELDS + 1) + [("note", "y" * 50_000)]
    feeder = _Feeder(_multipart(fields), chunk=1024)

    await _drive(app, feeder)

    assert feeder.status == 422
    assert feeder.events.count("receive") == len(feeder.chunks), "剩下的 body 要讀完丟棄"
    last_receive = max(i for i, e in enumerate(feeder.events) if e == "receive")
    assert feeder.events.index("send") > last_receive, "要先讀完 body 才回應"


async def test_body_已讀到結尾才拒絕時不再讀取():
    """最後一塊才超量：body 已讀完，再 `receive()` 會一直等到客戶端斷線。"""
    app, _ = _tiny_app()
    feeder = _Feeder(_multipart([("ids", "1")] * (UPLOAD_MAX_FIELDS + 1)), chunk=10**9)

    await _drive(app, feeder)

    assert feeder.status == 422
    assert feeder.read_after_end is False
    assert feeder.events.count("receive") == 1


# ── 解析錯誤與編碼（2026-10-29 security review H-1 / M-1）─────────────


async def test_客戶端中途斷線不是伺服器錯誤():
    """FastAPI 原本把它轉成 400；本層的解析在那之外，只攔超量的話會變成 500 並記 ERROR log——
    每次取消上傳、網路中斷都留一筆。"""
    app, received = _tiny_app()
    feeder = _Feeder(_multipart([("ids", "1")] * 50), chunk=64, disconnect_after=2)

    await _drive(app, feeder)  # 未處理的例外會在這裡拋出

    assert feeder.status == 422
    assert received == []
    assert feeder.read_after_end is False


@pytest.mark.parametrize(
    "body",
    [
        _multipart([("n" * 5000, "x")]),
        f"--{_BOUNDARY}\r\nno-colon-header\r\n\r\nx\r\n--{_BOUNDARY}--\r\n".encode(),
    ],
    ids=["標頭行過長", "標頭沒有冒號"],
)
async def test_格式損毀的表單回_422_不是_500(body):
    app, received = _tiny_app()

    r = await _post(app, "/upload", body, _CT)  # ASGITransport 預設把未處理的例外拋出來

    assert r.status_code == 422
    assert received == []


@pytest.mark.parametrize(
    "charset",
    ["punycode", "PunyCode", '"punycode"', "utf-8; charset=punycode", "latin-1"],
    ids=["punycode", "大小寫", "加引號", "重複參數-後者生效", "其他編碼"],
)
async def test_utf8_以外的編碼在解析前擋下(charset):
    """punycode 解碼是 O(n²)，200 個 64 KB 欄位可佔住事件迴圈 53.7 秒（security review 實測）。

    「重複參數」那條是**繞過**：標準函式庫讀到 utf-8、Starlette 讀到 punycode，檢查必須與
    Starlette 用同一個解析器。"""
    app, received = _tiny_app()
    headers = {"content-type": f"multipart/form-data; boundary={_BOUNDARY}; charset={charset}"}
    # ⚠️ 名稱與值要是**合法的** punycode（`note-` → `note`）：用 `note`／`x` 的話解碼會拋錯，被
    # 「解析錯誤一律 422」接住——本測試會通過，卻不是因為編碼檢查（變異檢查實測）
    body = _multipart([("note-", "x-")]) if "punycode" in charset.lower() else _multipart([("note", "x")])

    r = await _post(app, "/upload", body, headers)

    assert r.status_code == 422
    assert received == [], "不可交給解析器"


@pytest.mark.parametrize("charset", [None, "utf-8", "UTF-8", "utf8"], ids=["不帶", "utf-8", "大寫", "utf8"])
async def test_utf8_與不帶編碼照常放行(charset):
    """正向錨點：瀏覽器組的 `FormData` 不帶 charset。"""
    app, received = _tiny_app()
    ct = f"multipart/form-data; boundary={_BOUNDARY}" + (f"; charset={charset}" if charset else "")

    r = await _post(app, "/upload", _multipart([("note", "長")]), {"content-type": ct})

    assert r.status_code == 200, r.text
    assert received == [{"ids": 0, "note": 1, "file": None}]


# ── 守門：真正的 app ─────────────────────────────────────────────────


def _resolve(schema: dict, components: dict) -> dict:
    ref = schema.get("$ref")
    return components[ref.rsplit("/", 1)[-1]] if ref else schema


def _upload_operations() -> list[tuple[str, str, dict]]:
    """全部收檔案的寫入端點 (方法, 路徑, 表單 schema)，取自 OpenAPI（不走 `app.routes` 的理由見
    `test_core_upload_auth_precheck._operations`）。"""
    spec = real_app.openapi()
    components = spec["components"]["schemas"]
    ops = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            content = (op.get("requestBody") or {}).get("content", {})
            if "multipart/form-data" in content:
                ops.append((method.upper(), path, _resolve(content["multipart/form-data"]["schema"], components)))
    return ops


def _variants(prop: dict) -> list[dict]:
    """`anyOf`（`str | None` 之類）攤開成各個型別。"""
    return prop.get("anyOf", [prop])


def _is_file(prop: dict) -> bool:
    return any(v.get("format") == "binary" or v.get("contentMediaType") for v in _variants(prop))


def test_守門_掃得到收檔案的端點():
    """正向錨點：盤點若壞掉（掃到 0 支），下面的守門會空洞地通過。"""
    assert len(_upload_operations()) >= 5


@pytest.mark.parametrize(
    "body",
    [_multipart([("x", "1")] * (UPLOAD_MAX_FIELDS + 1)), _multipart([], files=UPLOAD_MAX_FILES + 1)],
    ids=["欄位過多", "檔案過多"],
)
@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _ in _upload_operations()])
async def test_守門_每支收檔案的端點都套用解析上限(method, path, body):
    """實際送超量欄位：所在 router 沒設 `route_class=LimitedFormRoute` 的話，會落到 Starlette 預設上限而放行。

    擋下發生在 body 解析，早於所有 dependency（身分、角色、DB），所以這裡不需要 DB。`get_db` 換成
    當場拋錯的版本：沒擋下的話請求會走到 dependency，回一個可辨識的錯誤，而不是在 unit 測試裡連 DB。
    """
    url = path.replace("{", "").replace("}", "")  # 路徑參數換成樣本值；型別轉換在解析 body 之後才做
    token = create_access_token(sub="ZT_FORM_LIMIT", ttl_minutes=5)
    headers = {**_CT, "authorization": f"Bearer {token}"}

    async def no_db():
        raise AppError(status_code=599, detail="未擋下、走到了 dependency", error_code="TEST_REACHED_DEPENDENCY")
        yield  # pragma: no cover

    real_app.dependency_overrides[get_db] = no_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=real_app), base_url="http://t") as client:
            r = await asyncio.wait_for(client.request(method, url, content=body, headers=headers), timeout=10)
    finally:
        real_app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 422, r.text
    assert json.loads(r.text) == {"error_code": "COMMON_422", "error_message": "上傳表單格式不符"}


@pytest.mark.parametrize(
    ("method", "path", "schema"), _upload_operations(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_守門_合法的表單不超過上限(method, path, schema):
    """上限是照合法表單的形狀定的。新增多值欄或調高 `maxItems`／`maxLength` 時，這裡會告訴你上限不夠了。"""
    props = schema["properties"].values()
    files = sum(1 for p in props if _is_file(p))
    fields = 0
    longest = 0
    for prop in props:
        if _is_file(prop):
            continue
        variants = _variants(prop)
        arrays = [v for v in variants if v.get("type") == "array"]
        assert not arrays or "maxItems" in arrays[0], f"{method} {path} 有沒有上限的多值欄，欄位數無從封頂"
        fields += arrays[0]["maxItems"] if arrays else 1
        lengths = [v["maxLength"] for v in variants if "maxLength" in v]
        longest = max([longest, *lengths])

    assert files <= UPLOAD_MAX_FILES
    assert fields + files <= UPLOAD_MAX_FIELDS, f"{method} {path} 合法最多 {fields + files} 個欄位"
    assert longest * 4 <= UPLOAD_MAX_PART_SIZE, f"{method} {path} 最長的欄位 {longest} 字（UTF-8 最多 4 bytes/字）"
