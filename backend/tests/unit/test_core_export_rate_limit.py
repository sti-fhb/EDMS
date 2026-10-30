"""匯出端點限流（#833 B4）。

匯出是整批撈資料、組 CSV，一次呼叫的成本是一般查詢的好幾倍，全程佔住一條 DB 連線；而連線池只有
15 條、後端只有一個 worker。ET 的三支 CSV 早已限流，DM 的三支匯出與 DP 稽核匯出原本沒有，
任何有權限的帳號連打就能佔滿連線池。比照 ET 週報匯出：每人每分鐘 10 次、每 IP 每分鐘 60 次。

另加「每人同時最多 1 支匯出」（security review M-1，2026-10-30 使用者裁示選項 1）：每分鐘次數擋不住
同一秒送出一批——三支 DM 匯出各 10 次就是 30 條連線，超過連線池的 15 條。
"""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from fastapi import Request
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


def _export_routes() -> list[APIRoute]:
    routes = [
        r
        for included in app.routes
        if type(included).__name__ == "_IncludedRouter"
        for r in included.original_router.routes
        if isinstance(r, APIRoute) and "GET" in r.methods and ("/export" in r.path or r.path.endswith(".csv"))
    ]
    # 正向錨點：與 OpenAPI 列出的匯出端點一一對上，避免展開方式失效時守門變成空集合而全綠
    openapi = {
        p for p, ops in app.openapi()["paths"].items() if "get" in ops and ("/export" in p or p.endswith(".csv"))
    }
    assert {r.path for r in routes} == openapi
    assert len(routes) >= 7
    return routes


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
