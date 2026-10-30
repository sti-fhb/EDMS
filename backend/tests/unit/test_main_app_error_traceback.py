"""`app_error_handler` 不讓模組層級 `AppError` 常數累積 traceback（#289 裁示 B）。

CPython raise 一個「已帶 `__traceback__` 的既有實例」時，會把本次傳播的 frame **附加**
上去而非取代。模組層級常數永遠被 module globals 持有 → 每次被拒絕的請求都多釘住一串
frame（含請求 body 與 `Authorization` header）。本檔以「同一路徑連續拒絕 N 次，
traceback 深度不成長」釘住 handler 的清理。

不需 integration：這是行程內記憶體行為，真 DB 幫不上忙。
"""

import traceback

import httpx
import pytest
from fastapi import FastAPI

from app.core.exceptions import AppError
from main import _release_tracebacks, app_error_handler

pytestmark = pytest.mark.unit

_ROUNDS = 20

#: 模擬各模組沿用的模組層級常數寫法。
_SINGLETON = AppError(status_code=404, detail="查無資料", error_code="TEST_001")
#: 「攔下再改拋」情境：內層被 `except AppError` 攔下，外層 `from None` 改拋。
_INNER = AppError(status_code=403, detail="無權限", error_code="TEST_002")
_OUTER = AppError(status_code=404, detail="查無資料", error_code="TEST_001")
#: 「攔下再以 `from exc` 改拋」情境：被攔的掛在 `__cause__`。
_CAUSE_INNER = AppError(status_code=403, detail="無權限", error_code="TEST_002")
_CAUSE_OUTER = AppError(status_code=404, detail="查無資料", error_code="TEST_001")


def _deep(level: int, exc: AppError) -> None:
    """拉出多層呼叫堆疊，讓累積量明顯（每次 raise 附加的 frame 數 ≈ 堆疊深度）。"""
    if level == 0:
        raise exc
    _deep(level - 1, exc)


def _depth(exc: BaseException | None) -> int:
    return len(traceback.extract_tb(exc.__traceback__)) if exc is not None else 0


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)

    @app.get("/singleton")
    async def singleton() -> None:
        _deep(4, _SINGLETON)

    @app.get("/chained")
    async def chained() -> None:
        try:
            _deep(4, _INNER)
        except AppError:
            raise _OUTER from None

    @app.get("/caused")
    async def caused() -> None:
        try:
            _deep(4, _CAUSE_INNER)
        except AppError as exc:
            raise _CAUSE_OUTER from exc

    return app


async def _hit(path: str, rounds: int = _ROUNDS) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return [await client.get(path) for _ in range(rounds)]


class TestTraceback不累積:
    async def test_同一個常數連續拒絕N次_traceback深度不成長(self) -> None:
        depths = []
        for _ in range(_ROUNDS):
            await _hit("/singleton", rounds=1)
            depths.append(_depth(_SINGLETON))
        # 不只「不成長」：請求結束後不再釘住任何 frame。
        assert depths == [0] * _ROUNDS

    async def test_被攔下再改拋的內層常數也不累積(self) -> None:
        """`raise X from None` 仍把被攔下的例外掛在 `X.__context__`（只是不顯示）。

        handler 若只清最外層，內層常數的 traceback 照樣每次成長——
        `et/learning/service.py` 的 `_require_access_by_course` 就是這個形狀。
        """
        await _hit("/chained")
        assert _OUTER.__context__ is _INNER
        assert _depth(_OUTER) == 0
        assert _depth(_INNER) == 0

    async def test_from_exc改拋的內層常數也不累積(self) -> None:
        """`raise X from exc` 掛在 `__cause__`——`learning/service.doc_file` 即此形狀。"""
        await _hit("/caused")
        assert _CAUSE_OUTER.__cause__ is _CAUSE_INNER
        assert _depth(_CAUSE_OUTER) == 0
        assert _depth(_CAUSE_INNER) == 0

    def test_串鏈互指成環時仍會結束並全部清掉(self) -> None:
        a = AppError(status_code=400, detail="a", error_code="TEST_A")
        b = AppError(status_code=400, detail="b", error_code="TEST_B")
        for exc in (a, b):
            try:
                raise exc
            except AppError:
                pass
        a.__context__, b.__context__ = b, a
        _release_tracebacks(a)
        assert a.__traceback__ is None
        assert b.__traceback__ is None


class TestHandler回應不變:
    async def test_清理不影響回應內容(self) -> None:
        responses = await _hit("/singleton", rounds=2)
        for resp in responses:
            assert resp.status_code == 404
            assert resp.json() == {"error_code": "TEST_001", "error_message": "查無資料"}
