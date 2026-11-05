"""匯出端點限流（#833 B4）。

匯出是整批撈資料、組 CSV，一次呼叫的成本是一般查詢的好幾倍，全程佔住一條 DB 連線；而連線池只有
15 條、後端只有一個 worker。ET 的三支 CSV 早已限流，DM 的三支匯出與 DP 稽核匯出原本沒有，
任何有權限的帳號連打就能佔滿連線池。比照 ET 週報匯出：每人每分鐘 10 次、每 IP 每分鐘 60 次。

另加「每人同時最多 1 支匯出」（security review M-1，2026-10-30 使用者裁示選項 1）：每分鐘次數擋不住
同一秒送出一批——三支 DM 匯出各 10 次就是 30 條連線，超過連線池的 15 條。
"""

import asyncio
import inspect
import json
from datetime import timedelta

import httpx
import pytest
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.routing import APIRoute

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.rate_limit import (
    EXPORT_IP_RATE_MAX,
    EXPORT_MAX_CONCURRENT_PER_USER,
    EXPORT_USER_RATE_MAX,
    SlidingWindowRateLimiter,
    limit_concurrent_exports,
    rate_limit_by_user,
)
from app.core.utils import utcnow
from app.dm.change_log import router as change_log_router
from app.dm.deps import DmContext, get_dm_context
from app.dm.kpi import router as kpi_router
from app.dm.obsolete_archive import router as obsolete_archive_router
from app.dp.audit import router as audit_router
from main import app

pytestmark = pytest.mark.unit

_429 = {"error_code": "COMMON_429", "error_message": "操作過於頻繁，請稍後再試"}


def _payload(sub: str) -> JwtPayload:
    now = utcnow()
    return JwtPayload(sub=sub, auth_time=now, iat=now, exp=now + timedelta(minutes=5))


# ── rate_limit_by_user 本身 ───────────────────────────────────────────────


async def test_同一人超過門檻回_429():
    dep = rate_limit_by_user(SlidingWindowRateLimiter(max_requests=2, window_seconds=60), "s")

    await dep(payload=_payload("ZT_A"))
    await dep(payload=_payload("ZT_A"))
    with pytest.raises(AppError) as exc:
        await dep(payload=_payload("ZT_A"))

    assert (exc.value.status_code, exc.value.error_code) == (429, "COMMON_429")


async def test_門檻以人計算_別人不受影響():
    dep = rate_limit_by_user(SlidingWindowRateLimiter(max_requests=1, window_seconds=60), "s")

    await dep(payload=_payload("ZT_A"))
    await dep(payload=_payload("ZT_B"))  # 不拋


async def test_不同_scope_各自計數():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

    await rate_limit_by_user(limiter, "s1")(payload=_payload("ZT_A"))
    await rate_limit_by_user(limiter, "s2")(payload=_payload("ZT_A"))  # 不拋


def test_匯出門檻比照_ET_週報匯出():
    assert (EXPORT_USER_RATE_MAX, EXPORT_IP_RATE_MAX) == (10, 60)


# ── 守門：所有匯出端點都要限流 ─────────────────────────────────────────────


def _named_like_export(path: str) -> bool:
    return "/export" in path or path.endswith(".csv")


def _is_file_download(route: APIRoute) -> bool:
    """把磁碟上的檔案串流出去（DM 文件、ET 教材文件與影片）：回傳型別或 `response_class` 是 `FileResponse`。

    這類不屬匯出限流的範圍：送檔前已交還 DB 連線（`core/db.release_db_before_streaming`，有守門），
    串流期間由 nginx 的下載並行上限管。⚠️ 應用層的限流並不一致：DM 三支沒有，ET 兩支只吃一般門檻
    （#905 B7 code review，已記入收尾摘要）。⚠️ 假設是「不整批撈 DB」——先查 DB 組成暫存檔再回
    `FileResponse` 的匯出會被這條豁免放過，寫那種端點時要自己掛匯出限流。
    """
    returns = inspect.signature(route.endpoint).return_annotation
    candidates = (returns, getattr(route.response_class, "value", route.response_class))
    return any(isinstance(c, type) and issubclass(c, FileResponse) for c in candidates)


def _is_export(route: APIRoute) -> bool:
    """GET、不是 204，且「路徑像匯出」或「沒有 `response_model`、又不是檔案下載」（#905 B8）。

    只看路徑的話，取名不同的匯出（如 `/report/download`）就漏掉了。`response_model` 是 None 代表回應
    不是 JSON 模型、是 handler 自己組的內容——這不依賴 handler 有沒有寫回傳型別註記（DM、DP 多數沒寫），
    也涵蓋 `PlainTextResponse` 等子類別。2026-11-05 實測：符合者正好是 7 支匯出加 5 支檔案下載。
    """
    if "GET" not in route.methods or route.status_code == 204:
        return False
    return _named_like_export(route.path) or (route.response_model is None and not _is_file_download(route))


def _export_routes() -> list[APIRoute]:
    routes = [
        r
        for included in app.routes
        if type(included).__name__ == "_IncludedRouter"
        for r in included.original_router.routes
        if isinstance(r, APIRoute) and _is_export(r)
    ]
    # 正向錨點：與 OpenAPI 列出的匯出端點一一對上，避免展開方式失效時守門變成空集合而全綠
    openapi = {p for p, ops in app.openapi()["paths"].items() if "get" in ops and _named_like_export(p)}
    assert {r.path for r in routes if _named_like_export(r.path)} == openapi
    assert len(routes) >= 7
    return routes


def _route(path: str, endpoint, **kwargs) -> APIRoute:
    router = APIRouter()
    router.add_api_route(path, endpoint, methods=["GET"], **kwargs)
    return router.routes[0]


async def _download() -> Response:  # pragma: no cover — 只看簽章
    return Response()


async def _no_annotation():  # pragma: no cover — 只看簽章
    return Response()


async def _stream() -> StreamingResponse:  # pragma: no cover — 只看簽章
    return StreamingResponse(iter([b""]))


@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (_download, {}),
        (_no_annotation, {"response_model": None}),
        (_stream, {}),
        (_no_annotation, {"response_class": PlainTextResponse, "response_model": None}),
    ],
    ids=["回傳 Response", "沒寫回傳型別", "StreamingResponse", "PlainTextResponse"],
)
def test_取名不像匯出但回傳自組內容者也算匯出(endpoint, kwargs):
    assert _is_export(_route("/api/x/report/download", endpoint, **kwargs))


def test_檔案下載不算匯出():
    async def file() -> FileResponse:  # pragma: no cover — 只看簽章
        return FileResponse("x")

    assert not _is_export(_route("/api/x/documents/{doc_id}/file", file))


def test_回_204_者不算匯出():
    assert not _is_export(_route("/api/x/ping", _download, status_code=204))


def test_回_JSON_模型者不算匯出():
    async def listing() -> dict:  # pragma: no cover — 只看簽章
        return {}

    assert not _is_export(_route("/api/x/items", listing, response_model=dict))


def _dependency_names(route: APIRoute) -> list[str]:
    names: list[str] = []
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        names.append(getattr(dep.call, "__qualname__", ""))
        stack.extend(dep.dependencies)
    return names


@pytest.mark.parametrize("route", _export_routes(), ids=lambda r: r.path)
def test_每支匯出端點都掛使用者與_IP_兩個維度的限流(route):
    """使用者維度擋單一帳號連打；IP 維度擋多開帳號（自助註冊是開的）。新增匯出端點時這條會提醒。"""
    names = _dependency_names(route)

    assert any(n.startswith(("rate_limit_by_user.", "rate_limit_by_et_user.")) for n in names), names
    assert any(n.startswith("rate_limit_by_ip.") for n in names), names


def _limiters(route: APIRoute, prefixes: tuple[str, ...]) -> list[SlidingWindowRateLimiter]:
    """該路由的限流 dependency 用到的限流器（取自工廠函式的閉包）。"""
    found: list[SlidingWindowRateLimiter] = []
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        stack.extend(dep.dependencies)
        if getattr(dep.call, "__qualname__", "").startswith(prefixes):
            cells = getattr(dep.call, "__closure__", None) or ()
            found.extend(c.cell_contents for c in cells if isinstance(c.cell_contents, SlidingWindowRateLimiter))
    return found


@pytest.mark.parametrize("route", _export_routes(), ids=lambda r: r.path)
def test_每支匯出端點的限流門檻不寬於匯出門檻(route):
    """掛了限流還不夠，門檻要是**匯出**的門檻（#905 B7）。

    ET 追蹤的兩支 CSV 原本只吃 router 層的一般查詢門檻（每人每分鐘 180 次），上面那條守門照樣綠。
    """
    user = _limiters(route, ("rate_limit_by_user.", "rate_limit_by_et_user."))
    ip = _limiters(route, ("rate_limit_by_ip.",))

    assert user and min(lim._max for lim in user) <= EXPORT_USER_RATE_MAX, [lim._max for lim in user]
    assert ip and min(lim._max for lim in ip) <= EXPORT_IP_RATE_MAX, [lim._max for lim in ip]


@pytest.mark.parametrize("route", _export_routes(), ids=lambda r: r.path)
def test_每支匯出端點都掛同時執行數上限(route):
    """所有匯出共用同一份「每人同時幾支」的計數；新增匯出端點時這條會提醒。"""
    assert "limit_concurrent_exports" in _dependency_names(route)


# ── 行為：新加限流的四支，第 11 次回 429 ───────────────────────────────────

_NEW = [
    ("/api/dm/change-log/entries/export", change_log_router),
    ("/api/dm/kpi/documents/export", kpi_router),
    ("/api/dm/obsolete-archive/documents/export", obsolete_archive_router),
    ("/api/dp/audit/logs/export", audit_router),
]


def _clear_export_limiters() -> None:
    for _, module in _NEW:
        module._export_user_limiter._hits.clear()
        module._export_ip_limiter._hits.clear()


_NO_PERMISSION = "ZT_NOPERM"
_HOLD: dict[str, asyncio.Event] = {}
_DM_VIEWER = "ZT_VIEWER"


@pytest.fixture
def overridden_app():
    """認證改讀測試標頭的使用者；DB 換成當場拋出的標記錯誤——回 599 代表「通過限流、走到了 DB」。

    模組閘（DM 的 `get_dm_context`、DP 稽核的 router-level 管理者閘）本來要查 DB，換成假的：
    使用者 ID 以 `ZT_NOPERM` 開頭者 403，其餘放行。
    """

    def _deny_if_no_permission(user: str) -> None:
        if user.startswith(_NO_PERMISSION):
            raise AppError(status_code=403, detail="無權限", error_code="TEST_NO_PERMISSION")

    async def fake_payload(request: Request) -> JwtPayload:
        return _payload(request.headers["x-test-user"])

    async def fake_admin_gate(request: Request) -> JwtPayload:
        _deny_if_no_permission(request.headers["x-test-user"])
        return _payload(request.headers["x-test-user"])

    async def fake_dm_context(request: Request) -> DmContext:
        user = request.headers["x-test-user"]
        _deny_if_no_permission(user)
        return DmContext(user_id=user, roles=frozenset({"DM_VIEWER" if user.startswith(_DM_VIEWER) else "DM_ADMIN"}))

    async def no_db(request: Request):
        if request.headers.get("x-test-hold"):  # 讓這個請求停在 handler 裡，模擬一支還在跑的匯出
            _HOLD["entered"].set()
            await _HOLD["release"].wait()
        raise AppError(status_code=599, detail="走到了 DB", error_code="TEST_REACHED_DB")
        yield  # pragma: no cover

    overrides = {
        get_jwt_payload: fake_payload,
        audit_router.router.dependencies[0].dependency: fake_admin_gate,
        get_dm_context: fake_dm_context,
        get_db: no_db,
    }
    app.dependency_overrides.update(overrides)
    _clear_export_limiters()
    try:
        yield app
    finally:
        _clear_export_limiters()
        for key in overrides:
            app.dependency_overrides.pop(key, None)


async def _get(client: httpx.AsyncClient, path: str, user: str) -> httpx.Response:
    return await client.get(path, headers={"x-test-user": user})


@pytest.mark.parametrize(("path", "module"), _NEW, ids=[p for p, _ in _NEW])
async def test_同一人第_11_次匯出回_429(overridden_app, path, module):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=overridden_app), base_url="http://t") as client:
        allowed = [(await _get(client, path, "ZT_U1")).status_code for _ in range(EXPORT_USER_RATE_MAX)]
        blocked = await _get(client, path, "ZT_U1")
        other = await _get(client, path, "ZT_U2")

    assert allowed == [599] * EXPORT_USER_RATE_MAX
    assert blocked.status_code == 429
    assert json.loads(blocked.text) == _429
    assert other.status_code == 599, "門檻以人計算，別人不受影響"


@pytest.mark.parametrize(("path", "module"), _NEW, ids=[p for p, _ in _NEW])
async def test_同一_IP_第_61_次匯出回_429(overridden_app, path, module):
    """每次換一個帳號，只有 IP 維度在累積——擋的是多開帳號繞過使用者維度。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=overridden_app), base_url="http://t") as client:
        allowed = [(await _get(client, path, f"ZT_IP{i}")).status_code for i in range(EXPORT_IP_RATE_MAX)]
        blocked = await _get(client, path, "ZT_IP_LAST")

    assert allowed == [599] * EXPORT_IP_RATE_MAX
    assert blocked.status_code == 429


@pytest.mark.parametrize(("path", "module"), _NEW, ids=[p for p, _ in _NEW])
async def test_無權限者不佔名額(overridden_app, path, module):
    """限流必須排在模組權限閘之後（code review MEDIUM）。

    否則任何人自助註冊一個沒有 DM 角色的帳號連打 60 次（每次 403），同一 NAT 出口的 DM 管理者就被 429。
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=overridden_app), base_url="http://t") as client:
        denied = [(await _get(client, path, f"{_NO_PERMISSION}{i}")).status_code for i in range(EXPORT_IP_RATE_MAX)]
        admin = await _get(client, path, "ZT_ADMIN")

    assert denied == [403] * EXPORT_IP_RATE_MAX
    assert admin.status_code == 599, "無權限者的請求不該把同一 IP 的名額用掉"


@pytest.mark.parametrize(("path", "module"), _NEW[:3], ids=[p for p, _ in _NEW[:3]])
async def test_有_DM_角色但非管理者也不佔名額(overridden_app, path, module):
    """DM 三支匯出限 DM_ADMIN；DM_VIEWER 等一般角色多數同仁都有，只排在 `get_dm_context` 之後擋不住（security M-2）。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=overridden_app), base_url="http://t") as client:
        denied = [(await _get(client, path, f"{_DM_VIEWER}{i}")).status_code for i in range(EXPORT_IP_RATE_MAX)]
        admin = await _get(client, path, "ZT_ADMIN")

    assert denied == [403] * EXPORT_IP_RATE_MAX
    assert json.loads((await _viewer_once(overridden_app, path)).text)["error_code"] == "DM_AUTH_003"
    assert admin.status_code == 599


async def _viewer_once(target, path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=target), base_url="http://t") as client:
        return await _get(client, path, f"{_DM_VIEWER}_MSG")


# ── 同時執行數 ────────────────────────────────────────────────────────────

_BUSY = {"error_code": "COMMON_429", "error_message": "已有匯出正在進行，請待完成後再試"}


async def test_同時執行數上限為每人_1_支():
    assert EXPORT_MAX_CONCURRENT_PER_USER == 1


async def test_同一人第二支匯出在第一支完成前回_429_且跨端點共用(overridden_app):
    """第一支停在 change-log 匯出裡；同一人改打 KPI 匯出也要被擋——名額是全部匯出共用的。"""
    _HOLD.update(entered=asyncio.Event(), release=asyncio.Event())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=overridden_app), base_url="http://t") as client:
        first = asyncio.create_task(
            client.get(_NEW[0][0], headers={"x-test-user": "ZT_C1", "x-test-hold": "1"}),
        )
        await asyncio.wait_for(_HOLD["entered"].wait(), timeout=5)

        second = await _get(client, _NEW[1][0], "ZT_C1")
        other = await _get(client, _NEW[1][0], "ZT_C2")

        _HOLD["release"].set()
        first_resp = await asyncio.wait_for(first, timeout=5)
        after = await _get(client, _NEW[1][0], "ZT_C1")

    assert second.status_code == 429
    assert json.loads(second.text) == _BUSY
    assert other.status_code == 599, "名額以人計算，別人不受影響"
    assert first_resp.status_code == 599
    assert after.status_code == 599, "第一支結束後名額歸還"


async def test_匯出拋錯時名額歸還():
    dep = limit_concurrent_exports
    gen = dep(payload=_payload("ZT_ERR"))
    await gen.__anext__()
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("匯出失敗"))

    again = dep(payload=_payload("ZT_ERR"))
    await again.__anext__()  # 不拋 429
    await again.aclose()


async def test_匯出被取消時名額歸還():
    """客戶端中途斷線時 handler 會被取消。"""
    gen = limit_concurrent_exports(payload=_payload("ZT_CANCEL"))
    await gen.__anext__()
    with pytest.raises(asyncio.CancelledError):
        await gen.athrow(asyncio.CancelledError())

    again = limit_concurrent_exports(payload=_payload("ZT_CANCEL"))
    await again.__anext__()
    await again.aclose()


# ── ET 追蹤的兩支 CSV（#905 B7）──────────────────────────────────────────

_TRACKING = ["/api/et/courses/1/students.csv", "/api/et/courses/1/survey-result.csv"]
_STUDENT_ONLY = "ZT_STUDENT"


@pytest.fixture
def tracking_app(overridden_app):
    """ET 存取閘換成假的：使用者 ID 以 `ZT_STUDENT` 開頭者只有學員角色（過不了教師閘），其餘為教師。"""
    from app.et import deps as et_deps
    from app.et.roles.authz import ET_TEACHER
    from app.et.tracking import router as tracking_router

    async def fake_et_context(request: Request) -> et_deps.EtContext:
        user = request.headers["x-test-user"]
        return et_deps.EtContext(
            user_id=user, roles=frozenset({"STUDENT" if user.startswith(_STUDENT_ONLY) else ET_TEACHER})
        )

    from app.et.reports import router as reports_router

    limiters = [
        tracking_router._user_limiter,
        tracking_router._ip_limiter,
        tracking_router._export_user_limiter,
        tracking_router._export_ip_limiter,
        tracking_router._heavy_user_limiter,
        tracking_router._heavy_ip_limiter,
        reports_router._user_limiter,
        reports_router._ip_limiter,
    ]
    for lim in limiters:
        lim._hits.clear()
    overridden_app.dependency_overrides[et_deps.get_et_context] = fake_et_context
    try:
        yield overridden_app
    finally:
        overridden_app.dependency_overrides.pop(et_deps.get_et_context, None)
        for lim in limiters:
            lim._hits.clear()


async def test_ET_追蹤_CSV_兩支共用匯出門檻_第_11_次回_429(tracking_app):
    """原本只吃一般查詢的每分鐘 180 次；兩支共用一份匯出計數。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tracking_app), base_url="http://t") as client:
        allowed = [(await _get(client, _TRACKING[i % 2], "ZT_T1")).status_code for i in range(EXPORT_USER_RATE_MAX)]
        blocked = await _get(client, _TRACKING[0], "ZT_T1")

    assert allowed == [599] * EXPORT_USER_RATE_MAX
    assert blocked.status_code == 429
    assert json.loads(blocked.text) == _429


@pytest.mark.parametrize("path", _TRACKING)
async def test_ET_追蹤_CSV_非教師不佔匯出名額(tracking_app, path):
    """匯出限流排在教師閘之後：學員（人人都有這個角色）連打不能把同一 IP 教師的名額用掉。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tracking_app), base_url="http://t") as client:
        denied = [(await _get(client, path, f"{_STUDENT_ONLY}{i}")).status_code for i in range(EXPORT_IP_RATE_MAX)]
        teacher = await _get(client, path, "ZT_TEACHER")

    assert denied == [403] * EXPORT_IP_RATE_MAX
    assert teacher.status_code == 599


async def test_ET_追蹤一般門檻也排在教師閘之後(tracking_app, monkeypatch):
    """router 層的一般門檻（每 IP 600）原本排在教師閘之前：4 個學員帳號連打就把同一 IP 的教師整頁擋成 429
    （#905 B7 security review M-1）。把門檻調小重現，免得真的打 600 次。"""
    from app.et.tracking import router as tracking_router

    monkeypatch.setattr(tracking_router._ip_limiter, "_max", 5)
    path = "/api/et/courses/1/students"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tracking_app), base_url="http://t") as client:
        denied = [(await _get(client, path, f"{_STUDENT_ONLY}{i}")).status_code for i in range(6)]
        teacher = await _get(client, path, "ZT_TEACHER")

    assert denied == [403] * 6
    assert teacher.status_code == 599, "學員被擋下的請求不該用掉同一 IP 教師的名額"


async def test_ET_週報匯出_非教師不佔名額(tracking_app):
    """週報的角色閘原本只在端點參數、最後才解析，學員在被 403 之前已記到匯出門檻（security review M-3）。"""
    path = "/api/et/reports/weekly/students.csv"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tracking_app), base_url="http://t") as client:
        denied = [(await _get(client, path, f"{_STUDENT_ONLY}{i}")).status_code for i in range(EXPORT_IP_RATE_MAX)]
        teacher = await _get(client, path, "ZT_TEACHER")

    assert denied == [403] * EXPORT_IP_RATE_MAX
    assert teacher.status_code == 599


_HEAVY = ["/api/et/courses/1/survey-result", "/api/et/courses/1/attempt-overview"]


@pytest.mark.parametrize("path", _HEAVY)
async def test_ET_重型讀取第_31_次回_429(tracking_app, path):
    """問卷結果 JSON 與 CSV 是同一份查詢、同一份具名文字答案；只吃一般門檻（180）的話改打 JSON 就繞過
    匯出門檻（security review M-2）。作答總覽同樣不分頁、一次撈全班。"""
    from app.et.tracking import router as tracking_router

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tracking_app), base_url="http://t") as client:
        allowed = [(await _get(client, path, "ZT_T1")).status_code for _ in range(tracking_router._HEAVY_USER_RATE)]
        blocked = await _get(client, path, "ZT_T1")

    assert allowed == [599] * tracking_router._HEAVY_USER_RATE
    assert blocked.status_code == 429


def test_ET_重型讀取門檻介於一般查詢與匯出之間():
    from app.et.tracking import router as tracking_router

    assert EXPORT_USER_RATE_MAX < tracking_router._HEAVY_USER_RATE < tracking_router._USER_RATE
    assert EXPORT_IP_RATE_MAX < tracking_router._HEAVY_IP_RATE < tracking_router._IP_RATE
