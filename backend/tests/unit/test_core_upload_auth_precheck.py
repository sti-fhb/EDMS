"""寫入請求在解析 body 之前先驗登入憑證（#810 第 1 項上傳端點、#833 C1 擴大到所有寫入）。

FastAPI 先解析 body（`await request.form()`）才跑 dependency，身分驗證也是 dependency——未登入者
因此能讓後端先收下最多 501MB 的檔案（落在容器的 /tmp）才被 401 擋下。
`UploadAuthPrecheckMiddleware` 在進路由之前先驗 token 的簽章與效期，未通過就丟棄 body、回 401。

本檔分三部分：
- middleware 行為：直接驅動 ASGI 介面，以「內層 app 沒被呼叫、body 在回應前被讀完丟棄」證明
  未登入的上傳到不了路由的解析
- 一般寫入（#833 C1）：JSON 寫入同樣先驗憑證；匿名端點清單與路由一致
- 清單守門：收檔案的路由 ↔ middleware 的路徑清單 ↔ nginx 的上傳 regex 三邊一致
"""

import asyncio
import json
import re
from pathlib import Path

import httpx
import jwt
import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.upload_auth_precheck import (
    ANONYMOUS_MAX_BODY_BYTES,
    ANONYMOUS_WRITE_ROUTES,
    UPLOAD_MAX_CONCURRENT_PER_USER,
    UPLOAD_METHODS,
    UPLOAD_PATH_PATTERN,
    UploadAuthPrecheckMiddleware,
)
from main import app
from tests.unit.test_route_auth_coverage import _iter_api_routes, _requires_jwt

pytestmark = pytest.mark.unit

_UPLOAD_PATH = "/api/et/materials/12/videos"
_CHUNKS = 3


class _Recorder:
    """記錄內層 app 是否被呼叫、body 被讀了幾塊，以及「讀」與「送」的先後順序。"""

    def __init__(self, *, disconnect_after: int | None = None) -> None:
        self.inner_called = False
        self.receive_calls = 0
        self.sent: list[dict] = []
        self.events: list[str] = []
        self._disconnect_after = disconnect_after

    async def receive(self) -> dict:
        self.receive_calls += 1
        self.events.append("receive")
        if self._disconnect_after is not None and self.receive_calls > self._disconnect_after:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"x" * 1024, "more_body": self.receive_calls < _CHUNKS}

    async def send(self, message: dict) -> None:
        self.events.append("send")
        self.sent.append(message)

    async def inner_app(self, scope, receive, send) -> None:
        self.inner_called = True
        await receive()
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"] == "http.response.start")

    @property
    def body(self) -> dict:
        return json.loads(b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body"))


def _scope(method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None, **extra) -> dict:
    return {"type": "http", "method": method, "path": path, "headers": headers or [], **extra}


async def _run(scope: dict, rec: _Recorder | None = None) -> _Recorder:
    rec = rec or _Recorder()
    await UploadAuthPrecheckMiddleware(rec.inner_app)(scope, rec.receive, rec.send)
    return rec


def _bearer(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode())]


def _assert_rejected(rec: _Recorder) -> None:
    """擋下的三個條件：回 401、body 沒交給路由、body 在回應**之前**讀完丟棄。

    「讀完才回應」不是多餘的：實測不讀 body 就回 401 時，nginx（上傳 location 串流不緩衝）會因上游
    提早關連線而對客戶端回 502，前端看不到 401（見 `upload_auth_precheck` 模組說明）。
    """
    assert rec.status == 401
    assert rec.body["error_code"] == "DP_AUTH_002"
    assert rec.inner_called is False, "body 不可交給路由解析"
    assert rec.receive_calls == _CHUNKS, "body 要讀完丟棄，否則 nginx 回 502"
    last_receive = max(i for i, e in enumerate(rec.events) if e == "receive")
    assert rec.events.index("send") > last_receive, "要先讀完 body 才回應"


# ── middleware 行為 ─────────────────────────────────────────────────


async def test_未帶憑證上傳_丟棄_body_回_401():
    _assert_rejected(await _run(_scope("POST", _UPLOAD_PATH)))


@pytest.mark.parametrize(
    "header",
    [
        [(b"authorization", b"Bearer not-a-jwt")],
        [(b"authorization", b"Basic dXNlcjpwYXNz")],
        [(b"authorization", b"Bearer")],
        [(b"authorization", b"Bearer    ")],
    ],
    ids=["竄改或亂填的-token", "非-Bearer-scheme", "Bearer-後沒有-token", "Bearer-後只有空白"],
)
async def test_憑證無效時上傳_丟棄_body_回_401(header):
    _assert_rejected(await _run(_scope("PUT", "/api/dm/documents/DM-SOP-000001/versions/1", header)))


async def test_影片播放票不可當上傳憑證():
    """帶 `typ` 的專用票券（ET 影片播放票）會出現在 URL 與 log，不可換到上傳權。"""
    ticket = jwt.encode(
        {"sub": "u1", "typ": "video", "exp": 9_999_999_999}, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM
    )
    _assert_rejected(await _run(_scope("POST", _UPLOAD_PATH, _bearer(ticket))))


async def test_客戶端中途斷線即停止讀取():
    """丟棄 body 時遇到 `http.disconnect` 就停，不在已斷線的連線上空轉。"""
    rec = await _run(_scope("POST", _UPLOAD_PATH), _Recorder(disconnect_after=1))

    assert rec.receive_calls == 2
    assert rec.inner_called is False


async def test_有子路徑前綴_root_path_時仍會預檢():
    """Starlette 比對路由前會扣掉 `root_path`；本層不扣的話以子路徑部署時整個失效（security review）。"""
    _assert_rejected(await _run(_scope("POST", "/edms" + _UPLOAD_PATH, root_path="/edms")))


@pytest.mark.parametrize(
    "template",
    ["Bearer {t}", "bearer {t}", "Bearer  {t} "],
    ids=["標準", "scheme-小寫", "token-前後有空白"],
)
async def test_有效憑證放行_帳號狀態仍由原本的身分依賴檢查(template):
    """正向錨點：上面「不放行」的斷言不是建立在「一律擋下」上。

    解析方式比照 FastAPI `HTTPBearer`（scheme 不分大小寫、token 去頭尾空白）——兩邊不一致會出現
    「這裡擋下、路由其實接受」的誤擋。本 middleware 只驗簽章與效期；停用 / 鎖定仍在 `get_jwt_payload`。
    """
    token = create_access_token(sub="u1", ttl_minutes=15)
    rec = await _run(_scope("POST", _UPLOAD_PATH, [(b"authorization", template.format(t=token).encode())]))

    assert rec.inner_called is True
    assert rec.status == 201


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/dm/documents"),
        ("GET", "/api/dm/documents/DM-SOP-000001/versions"),
        ("POST", "/api/login"),
        ("POST", "/api/register"),
        ("POST", "/edms/api/login"),
        ("POST", "/health"),
    ],
    ids=["文件清單-GET", "版本清單-GET", "登入", "自助註冊", "子路徑前綴下的登入", "非-api-路徑"],
)
async def test_讀取與匿名端點不經本檢查_原樣交給路由(method, path):
    """GET 的身分驗證維持原狀（沒有 body 要解析）；匿名的寫入端點本來就不需要憑證。"""
    extra = {"root_path": "/edms"} if path.startswith("/edms") else {}
    rec = await _run(_scope(method, path, **extra))

    assert rec.inner_called is True


# ── 一般寫入（#833 C1）──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/dm/documents/DM-SOP-000001/submit"),
        ("PUT", "/api/dp/user/me"),
        ("PATCH", "/api/et/courses/1"),
        ("DELETE", "/api/et/courses/1/chapters/2"),
        ("POST", "/api/no-such-route"),
        ("POST", "/api/login/"),
    ],
    ids=["POST", "PUT", "PATCH", "DELETE", "不存在的路徑", "匿名端點帶尾斜線"],
)
async def test_一般寫入未帶憑證_丟棄_body_回_401(method, path):
    """FastAPI 先解析 JSON body 才跑身分依賴；未登入者可讓後端解析最多 2MB（nginx 上限）才被擋（#817 M2）。

    不存在的路徑也先回 401 而不是 404：不先驗就得先比對路由，而這裡刻意不依賴路由表（見模組說明）。
    匿名端點帶尾斜線同理（改前是 307 轉址），刻意不正規化，見模組說明。
    """
    _assert_rejected(await _run(_scope(method, path)))


async def test_一般寫入帶有效憑證放行():
    token = create_access_token(sub="u1", ttl_minutes=15)
    rec = await _run(_scope("POST", "/api/dm/documents/DM-SOP-000001/submit", _bearer(token)))

    assert rec.inner_called is True
    assert rec.status == 201


async def test_一般寫入不佔同時上傳名額():
    """同時上傳數上限只管收檔案的端點；一般寫入同時多支照常進得去。"""
    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    token = create_access_token(sub="u1", ttl_minutes=15)
    tasks = []
    for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER + 1):
        rec = _Recorder()
        scope = _scope("POST", "/api/dm/documents/DM-SOP-000001/submit", _bearer(token))
        tasks.append(asyncio.create_task(mw(scope, rec.receive, rec.send)))
        await asyncio.sleep(0)

    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER + 1
    assert mw._in_flight == {}
    gate.release.set()
    await asyncio.gather(*tasks)


async def test_真的_app_未登入送壞掉的_JSON_回_401_而不是_422():
    """因果鏈終點：改前 FastAPI 先解析 body，壞掉的 JSON 回 422（代表已經解析過了）；改後在解析前就 401。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.put("/api/dp/user/me", content=b"{not json", headers={"content-type": "application/json"})

    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "DP_AUTH_002"


async def test_真的_app_匿名端點仍到得了路由():
    """正向錨點：登入送壞掉的 JSON 照舊由路由解析、回 422——上一條的 401 不是「一律擋下」造成的。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/api/login", content=b"{not json", headers={"content-type": "application/json"})

    assert r.status_code == 422, r.text


# ── 匿名寫入的 body 上限（#833 C1 security review MEDIUM-1）──────────


class _BodyFeeder:
    """以固定大小的塊送出 body，記錄內層 app 實際收到的內容。"""

    def __init__(self, total: int, chunk: int = 16 * 1024, *, disconnect_at: int | None = None) -> None:
        self._remaining = total
        self._chunk = chunk
        self._disconnect_at = disconnect_at
        self.receive_calls = 0
        self.sent: list[dict] = []
        self.inner_body: bytes | None = None

    async def receive(self) -> dict:
        self.receive_calls += 1
        if self._disconnect_at is not None and self.receive_calls > self._disconnect_at:
            return {"type": "http.disconnect"}
        size = min(self._chunk, self._remaining)
        self._remaining -= size
        return {"type": "http.request", "body": b"a" * size, "more_body": self._remaining > 0}

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    async def inner_app(self, scope, receive, send) -> None:
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        self.inner_body = body
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"] == "http.response.start")


async def _anonymous(feeder: _BodyFeeder) -> _BodyFeeder:
    await UploadAuthPrecheckMiddleware(feeder.inner_app)(_scope("POST", "/api/login"), feeder.receive, feeder.send)
    return feeder


async def test_匿名寫入_body_超過上限_丟棄_回_413():
    """匿名端點不經本層的身分預檢，是未登入者唯一還能讓後端解析 JSON 的入口；不設上限的話 C1 只做了一半。"""
    feeder = await _anonymous(_BodyFeeder(ANONYMOUS_MAX_BODY_BYTES + 1))

    assert feeder.status == 413
    assert feeder.inner_body is None, "超量的 body 不可交給路由解析"
    assert feeder._remaining == 0, "body 要讀完丟棄"


async def test_匿名寫入_body_在上限內原樣交給路由():
    """正向錨點：上限內的 body 一個位元組都不少（本層先收齊再轉交）。"""
    feeder = await _anonymous(_BodyFeeder(ANONYMOUS_MAX_BODY_BYTES))

    assert feeder.status == 200
    assert feeder.inner_body == b"a" * ANONYMOUS_MAX_BODY_BYTES


async def test_匿名寫入_收齊前斷線即停止():
    feeder = await _anonymous(_BodyFeeder(ANONYMOUS_MAX_BODY_BYTES, disconnect_at=1))

    assert feeder.inner_body is None
    assert feeder.receive_calls == 2


def test_匿名寫入上限容得下最大的合法請求():
    """最大的合法匿名請求：設定密碼類（兩個 4096 字的密碼 + 200 字的 token）。

    以最壞的 JSON 編碼估：每個字都是 BMP 外的字元、跳脫成一對 surrogate（12 bytes）。前端
    `JSON.stringify` 不跳脫非 ASCII，實際最多約 32KB；這裡取最壞情況，讓上限不必依賴前端的編碼方式。
    密碼上限改大時這條會紅。
    """
    from app.dp.user.schemas import VerifyEmailRequest

    def max_len(field: str) -> int:
        meta = VerifyEmailRequest.model_fields[field].metadata
        return next(m.max_length for m in meta if getattr(m, "max_length", None))

    password = "\U0001f600" * max_len("new_password")
    body = json.dumps(
        {"token": "t" * max_len("token"), "new_password": password, "confirm_password": password},
        ensure_ascii=True,
    ).encode()
    assert len(body) <= ANONYMOUS_MAX_BODY_BYTES, f"最大合法請求 {len(body)} bytes 超過上限"


async def test_真的_app_匿名端點送超量_body_回_413():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post(
            "/api/login", content=b" " * (ANONYMOUS_MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
        )

    assert r.status_code == 413, r.text
    assert r.json()["error_code"] == "COMMON_413"


def test_守門_匿名寫入清單與路由一致():
    """`ANONYMOUS_WRITE_ROUTES` 必須正好是「不經 `get_jwt_payload` 的寫入路由」。

    少列：該匿名端點被本層擋成 401（例如登入壞掉）。多列：本該先驗的端點被放過。
    路由的認證判定沿用 `test_route_auth_coverage` 的掃描（它也是匿名端點的權威清單）。
    """
    anonymous_writes = {
        (method, route.path)
        for route, inherited in _iter_api_routes()
        if route.path.startswith("/api/") and not _requires_jwt(route, inherited)
        for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert len(anonymous_writes) >= 5, "正向錨點：掃描若失效（0 條）這條會空洞地通過"
    assert set(ANONYMOUS_WRITE_ROUTES) == anonymous_writes


# ── 每位使用者同時上傳數上限（#833 A3）─────────────────────────────


class _Gate:
    """內層 app 停在「上傳進行中」直到放行，用來製造同時進行的上傳。"""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.entered = 0

    async def inner_app(self, scope, receive, send) -> None:
        self.entered += 1
        await self.release.wait()
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _as(sub: str) -> dict:
    return _scope("POST", _UPLOAD_PATH, _bearer(create_access_token(sub=sub, ttl_minutes=15)))


async def _start(mw: UploadAuthPrecheckMiddleware, sub: str) -> tuple[asyncio.Task, _Recorder]:
    rec = _Recorder()
    task = asyncio.create_task(mw(_as(sub), rec.receive, rec.send))
    await asyncio.sleep(0)
    return task, rec


async def test_同一人同時上傳超過上限_丟棄_body_回_429():
    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    running = [await _start(mw, "u1") for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER)]
    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER, "前置：上限內的上傳都進得去"

    rejected = _Recorder()
    # 逾時：沒擋下的話它會進到內層、停在閘門前，測試要紅而不是卡住
    await asyncio.wait_for(mw(_as("u1"), rejected.receive, rejected.send), timeout=5)

    assert rejected.status == 429
    assert rejected.body["error_code"] == "COMMON_429"
    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER, "超量的那個不可交給路由"
    assert rejected.receive_calls == _CHUNKS, "body 要讀完丟棄，否則 nginx 回 502"
    gate.release.set()
    await asyncio.gather(*(t for t, _ in running))


async def test_上限以人計算_別人的上傳不受影響():
    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    running = [await _start(mw, "u1") for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER)]

    other, _ = await _start(mw, "u2")

    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER + 1
    gate.release.set()
    await asyncio.gather(*(t for t, _ in running), other)


async def test_上傳結束後名額歸還_含路由拋錯的情況():
    """名額沒歸還的話，那個人從此再也上傳不了——直到後端重啟。"""
    calls = []

    async def failing_then_ok(scope, receive, send):
        calls.append(1)
        if len(calls) <= UPLOAD_MAX_CONCURRENT_PER_USER:
            raise RuntimeError("路由內部錯誤")
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = UploadAuthPrecheckMiddleware(failing_then_ok)
    for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER):
        with pytest.raises(RuntimeError):
            await mw(_as("u1"), _Recorder().receive, _Recorder().send)

    rec = _Recorder()
    await mw(_as("u1"), rec.receive, rec.send)

    assert rec.status == 201
    assert mw._in_flight == {}, "歸零的鍵要移除，計數表不隨使用者數累積"


async def test_上傳被取消時名額也歸還():
    """`CancelledError` 不是 `Exception` 的子類，只靠 `except Exception` 會漏掉這條（code review）。"""
    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    running = [await _start(mw, "u1") for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER)]
    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER

    for task, _ in running:
        task.cancel()
    await asyncio.gather(*(t for t, _ in running), return_exceptions=True)

    assert mw._in_flight == {}
    after, _ = await _start(mw, "u1")
    assert gate.entered == UPLOAD_MAX_CONCURRENT_PER_USER + 1, "取消後名額歸還，同一人可以再上傳"
    gate.release.set()
    await after


async def test_非_http_的_scope_原樣放行():
    rec = _Recorder()
    called = []

    async def inner(scope, receive, send):
        called.append(scope["type"])

    await UploadAuthPrecheckMiddleware(inner)({"type": "lifespan"}, rec.receive, rec.send)

    assert called == ["lifespan"]


# ── 清單守門：路由 ↔ middleware ↔ nginx ─────────────────────────────


def _sample(path: str) -> str:
    """把路徑參數換成樣本值，供 regex 比對（`{doc_id}` → `X1`）。"""
    return re.sub(r"\{[^}]+\}", "X1", path)


def _operations() -> list[tuple[str, str, bool]]:
    """全部 API 的 (方法, 路徑, 是否收檔案)，取自 OpenAPI。

    ⚠️ 不走 `app.routes`：FastAPI 0.139 起子 router 包成私有的 `_IncludedRouter`，第一層只看得到
    3 條路由（曾因此掃到 0 支上傳端點、守門空洞地通過）。OpenAPI 是公開且展開後的結果。
    前提：沒有路由設 `include_in_schema=False`，也沒有只收 `application/x-www-form-urlencoded`
    （無檔案欄位）的 Form 端點——目前兩者全專案皆 0 處，日後若有要另補。
    """
    ops: list[tuple[str, str, bool]] = []
    for path, methods in app.openapi()["paths"].items():
        for method, op in methods.items():
            content = (op.get("requestBody") or {}).get("content", {})
            ops.append((method.upper(), path, "multipart/form-data" in content))
    return ops


_WRITE = {"POST", "PUT", "PATCH"}


_UPLOAD_INCLUDE = "include /etc/nginx/api-upload.conf;"


def _nginx_conf() -> str:
    return (Path(__file__).resolve().parents[3] / "nginx" / "nginx.conf").read_text(encoding="utf-8")


def _nginx_upload_patterns() -> list[re.Pattern[str]]:
    """`nginx/nginx.conf` 中 include `api-upload.conf` 的 regex location（取每個 include 之前最近的 location）。"""
    conf = _nginx_conf()
    patterns = []
    for m in re.finditer(re.escape(_UPLOAD_INCLUDE), conf):
        locations = re.findall(r"location ~ (\S+) \{", conf[: m.start()])
        patterns.append(re.compile(locations[-1]))
    return patterns


def test_守門_掃得到收檔案的路由():
    """正向錨點：盤點若壞掉（掃到 0 支），下面三條會空洞地通過——實際發生過一次。"""
    assert len([1 for _, _, multipart in _operations() if multipart]) >= 5


def test_守門_收檔案的寫入路由都在預檢範圍內():
    missing = [
        f"{m} {p}"
        for m, p, multipart in _operations()
        if multipart and m in _WRITE and not (m in UPLOAD_METHODS and UPLOAD_PATH_PATTERN.match(_sample(p)))
    ]
    assert missing == [], f"新增上傳端點要加進 app/core/upload_auth_precheck.py：{missing}"


def test_守門_預檢範圍內的寫入路由都是收檔案的():
    """反向：預檢對 JSON 端點沒有壞處，但清單多列會讓下一個人誤以為那支是上傳端點。"""
    extra = [
        f"{m} {p}"
        for m, p, multipart in _operations()
        if m in UPLOAD_METHODS and UPLOAD_PATH_PATTERN.match(_sample(p)) and not multipart
    ]
    assert extra == []


def test_守門_nginx_的上傳_regex_與路由一致():
    """nginx 設定 CI 不驗；漏列的上傳端點在線上會被 2m 上限擋成 413（#806）。"""
    patterns = _nginx_upload_patterns()
    # 與 include 次數相等，不只是 `>= 2`：日後新增第三個上傳 location 卻沒被解析到時要紅
    assert len(patterns) == _nginx_conf().count(_UPLOAD_INCLUDE) >= 2

    def in_nginx(path: str) -> bool:
        return any(rx.match(_sample(path)) for rx in patterns)

    ops = _operations()
    not_in_nginx = sorted(f"{m} {p}" for m, p, multipart in ops if multipart and m in _WRITE and not in_nginx(p))
    assert not_in_nginx == [], f"新增上傳端點要加進 nginx/nginx.conf 的上傳 location：{not_in_nginx}"

    not_upload = sorted(f"{m} {p}" for m, p, multipart in ops if m in _WRITE and in_nginx(p) and not multipart)
    assert not_upload == [], f"nginx 上傳 location 命中非上傳的寫入路由（會被 415 擋下）：{not_upload}"
