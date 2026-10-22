"""上傳端點在解析 body 之前先驗登入憑證（#810 第 1 項）。

FastAPI 先解析 body（`await request.form()`）才跑 dependency，身分驗證也是 dependency——未登入者
因此能讓後端先收下最多 501MB 的檔案（落在容器的 /tmp）才被 401 擋下。
`UploadAuthPrecheckMiddleware` 在進路由之前先驗 token 的簽章與效期，未通過就丟棄 body、回 401。

本檔分兩部分：
- middleware 行為：直接驅動 ASGI 介面，以「內層 app 沒被呼叫、body 在回應前被讀完丟棄」證明
  未登入的上傳到不了路由的解析
- 清單守門：收檔案的路由 ↔ middleware 的路徑清單 ↔ nginx 的上傳 regex 三邊一致
"""

import json
import re
from pathlib import Path

import jwt
import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.upload_auth_precheck import UPLOAD_METHODS, UPLOAD_PATH_PATTERN, UploadAuthPrecheckMiddleware
from main import app

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
        ("POST", "/api/dm/documents/DM-SOP-000001/submit"),
        ("POST", "/api/login"),
    ],
    ids=["文件清單-GET", "版本清單-GET", "非上傳的-POST", "登入"],
)
async def test_非上傳請求不經本檢查_原樣交給路由(method, path):
    """一般請求的身分驗證維持原狀（登入端點本來就不需要憑證）。"""
    rec = await _run(_scope(method, path))

    assert rec.inner_called is True


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
