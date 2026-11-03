"""上傳前檢查磁碟剩餘空間（#905 A1）。

後端的上傳暫存（`/tmp`）、DM 檔案與 ET 影片的存放區，在正式環境與 TBMS 的資料庫共用同一顆磁碟；
寫滿會讓 TBMS 的資料庫也寫不進去。`UploadAuthPrecheckMiddleware` 在交給路由解析 body 之前，先看
這幾個目錄中最少的剩餘空間，低於 `UPLOAD_MIN_FREE_DISK_MB` 就丟棄 body、回 507。

剩餘空間以替身注入；真的呼叫 `shutil.disk_usage` 的路徑另有一條（`test_真的磁碟_*`）。
"""

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path

import pytest

from app.core import upload_disk_guard
from app.core.auth import create_access_token
from app.core.config import settings
from app.core.upload_auth_precheck import UPLOAD_MAX_CONCURRENT_PER_USER, UploadAuthPrecheckMiddleware

pytestmark = pytest.mark.unit

_MB = 1024 * 1024
_UPLOAD_PATH = "/api/et/materials/12/videos"
_CHUNKS = 3


class _Recorder:
    """記錄內層 app 是否被呼叫、body 被讀了幾塊，以及「讀」與「送」的先後順序。"""

    def __init__(self) -> None:
        self.inner_called = False
        self.receive_calls = 0
        self.sent: list[dict] = []
        self.events: list[str] = []

    async def receive(self) -> dict:
        self.receive_calls += 1
        self.events.append("receive")
        return {"type": "http.request", "body": b"x" * 1024, "more_body": self.receive_calls < _CHUNKS}

    async def send(self, message: dict) -> None:
        self.events.append("send")
        self.sent.append(message)

    async def inner_app(self, scope, receive, send) -> None:
        self.inner_called = True
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"] == "http.response.start")

    @property
    def body(self) -> dict:
        return json.loads(b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body"))


def _request(method: str = "POST", path: str = _UPLOAD_PATH) -> dict:
    token = create_access_token(sub="u1", ttl_minutes=15)
    return {"type": "http", "method": method, "path": path, "headers": [(b"authorization", f"Bearer {token}".encode())]}


async def _run(scope: dict, mw: UploadAuthPrecheckMiddleware | None = None) -> _Recorder:
    rec = _Recorder()
    await (mw or UploadAuthPrecheckMiddleware(rec.inner_app))(scope, rec.receive, rec.send)
    return rec


_ET_NEED_MB = upload_disk_guard.ET_VIDEO_MAX_BODY_MB * 2
_DM_NEED_MB = upload_disk_guard.DM_DOCUMENT_MAX_BODY_MB * 2
_THRESHOLD_MB = 10 * 1024


@pytest.fixture(autouse=True)
def _fresh_reject_log(monkeypatch):
    """log 頻率限制是模組層級的狀態；每條測試從「從未記過」開始。"""
    monkeypatch.setattr(upload_disk_guard, "_reject_log", upload_disk_guard._RejectLog())


@pytest.fixture
def threshold(monkeypatch):
    """門檻設為 10 GB（正式環境的預設值）；測試環境的 conftest 預設為 0（關閉）。"""
    monkeypatch.setattr(settings, "UPLOAD_MIN_FREE_DISK_MB", 10 * 1024)


def _free(monkeypatch, mapping: dict[str, int]) -> list[str]:
    """以替身回報各目錄的剩餘空間（MB）；回傳實際被查詢的目錄，供斷言。"""
    asked: list[str] = []
    dirs = upload_disk_guard.upload_dirs()

    def fake(path: str) -> int:
        asked.append(path)
        for key, mb in mapping.items():
            if path == dirs[key]:
                return mb * _MB
        return 100 * 1024 * _MB

    monkeypatch.setattr(upload_disk_guard, "_free_bytes", fake)
    return asked


# ── middleware 行為 ─────────────────────────────────────────────────


@pytest.mark.usefixtures("threshold")
async def test_剩餘空間低於門檻_丟棄_body_回_507_並記_error(monkeypatch, caplog):
    _free(monkeypatch, {"et": 9 * 1024})
    with caplog.at_level(logging.ERROR):
        rec = await _run(_request())

    assert rec.status == 507
    assert rec.body["error_code"] == "COMMON_507"
    assert rec.inner_called is False, "body 不可交給路由解析（解析就會寫進 /tmp）"
    assert rec.receive_calls == _CHUNKS, "body 要讀完丟棄，否則 nginx 回 502"
    last_receive = max(i for i, e in enumerate(rec.events) if e == "receive")
    assert rec.events.index("send") > last_receive, "要先讀完 body 才回應"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, "維運要從 log 看得到上傳被暫停"
    assert "9216" in errors[0].getMessage(), "要記下剩餘多少"


@pytest.mark.usefixtures("threshold")
async def test_剩餘空間扣掉這一支後仍達門檻_照常交給路由(monkeypatch, caplog):
    """邊界：剩餘 = 門檻 + 這一支的預留，恰好放行。"""
    exact = _THRESHOLD_MB + _ET_NEED_MB
    _free(monkeypatch, {"tmp": exact, "dm": exact, "et": exact})
    with caplog.at_level(logging.WARNING):
        rec = await _run(_request())

    assert rec.status == 201
    assert rec.inner_called is True
    assert not caplog.records


@pytest.mark.usefixtures("threshold")
@pytest.mark.parametrize("low", ["tmp", "dm", "et"])
async def test_任一個上傳目錄不足就擋(monkeypatch, low):
    """三處在正式環境是同一顆磁碟，但部署方式改了（例如影片改掛獨立磁碟）時要各自看。"""
    asked = _free(monkeypatch, {low: 1024})
    rec = await _run(_request())

    assert rec.status == 507
    assert sorted(asked) == sorted(upload_disk_guard.upload_dirs().values()), "三處都要量"


@pytest.mark.usefixtures("threshold")
@pytest.mark.parametrize(
    ("method", "path"),
    [("PUT", "/api/dp/user/me"), ("POST", "/api/dm/documents/DM-SOP-000001/submit"), ("GET", _UPLOAD_PATH)],
    ids=["一般寫入", "DM 非上傳的寫入", "上傳路徑的讀取"],
)
async def test_非上傳請求不檢查磁碟(monkeypatch, method, path):
    """磁碟滿了仍要能登入、改資料、看文件——擋的只是會寫檔的請求。"""
    asked = _free(monkeypatch, {"tmp": 0, "dm": 0, "et": 0})
    rec = await _run(_request(method, path))

    assert rec.inner_called is True
    assert asked == []


async def test_門檻為_0_時不檢查(monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_MIN_FREE_DISK_MB", 0)
    asked = _free(monkeypatch, {"tmp": 0, "dm": 0, "et": 0})
    rec = await _run(_request())

    assert rec.status == 201
    assert asked == []


@pytest.mark.usefixtures("threshold")
async def test_未登入仍先回_401_不洩漏磁碟狀態(monkeypatch):
    """順序：先驗身分。未登入者不該能探測主機磁碟是否將滿。"""
    _free(monkeypatch, {"tmp": 0})
    rec = _Recorder()
    scope = {"type": "http", "method": "POST", "path": _UPLOAD_PATH, "headers": []}
    await UploadAuthPrecheckMiddleware(rec.inner_app)(scope, rec.receive, rec.send)

    assert rec.status == 401


@pytest.mark.usefixtures("threshold")
async def test_被拒絕的上傳不佔同時上傳名額(monkeypatch):
    """磁碟恢復後，同一人要能立刻上傳；名額沒歸還的話要等後端重啟。"""
    _free(monkeypatch, {"et": 0})
    rec = _Recorder()
    mw = UploadAuthPrecheckMiddleware(rec.inner_app)
    for _ in range(UPLOAD_MAX_CONCURRENT_PER_USER + 1):
        assert (await _run(_request(), mw)).status == 507

    assert mw._in_flight == {}
    _free(monkeypatch, {})
    assert (await _run(_request(), mw)).status == 201


@pytest.mark.usefixtures("threshold")
async def test_剩餘空間不夠這一支的預留就擋(monkeypatch):
    """剩餘比門檻多，但不夠這支影片寫完：寫完之後就會跌破門檻。"""
    _free(monkeypatch, {"et": _THRESHOLD_MB + _ET_NEED_MB - 1})

    assert (await _run(_request())).status == 507


@pytest.mark.usefixtures("threshold")
async def test_文件的預留比影片小(monkeypatch):
    """同樣的剩餘空間，DM 文件（51 MB）放得下、ET 影片（501 MB）放不下。"""
    _free(monkeypatch, {"tmp": _THRESHOLD_MB + _DM_NEED_MB, "dm": _THRESHOLD_MB + _DM_NEED_MB})

    assert (await _run(_request("POST", "/api/dm/documents"))).status == 201
    assert (await _run(_request())).status == 507


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


@pytest.mark.usefixtures("threshold")
async def test_進行中的上傳會佔預留_結束後歸還(monkeypatch):
    """同一瞬間開始的上傳都還沒寫入任何位元組；不算預留的話，剩餘空間只夠一支也會兩支都放行。"""
    _free(monkeypatch, {"et": _THRESHOLD_MB + _ET_NEED_MB + _ET_NEED_MB // 2})
    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    first = asyncio.create_task(mw(_request(), _Recorder().receive, _Recorder().send))
    await asyncio.sleep(0)
    assert gate.entered == 1, "前置：第一支放得下"

    second = _Recorder()
    await asyncio.wait_for(mw(_request(), second.receive, second.send), timeout=5)
    assert second.status == 507, "第一支還在寫，剩下的不夠第二支"
    assert gate.entered == 1

    gate.release.set()
    await first
    assert mw._reserved_bytes == 0, "回應結束要扣回預留"
    gate.release = asyncio.Event()
    third = asyncio.create_task(mw(_request(), _Recorder().receive, _Recorder().send))
    await asyncio.sleep(0)
    assert gate.entered == 2, "第一支結束後，同樣的剩餘空間又放得下一支"
    gate.release.set()
    await third


@pytest.mark.usefixtures("threshold")
async def test_路由拋錯或被取消時預留也扣回(monkeypatch):
    _free(monkeypatch, {})

    async def failing(scope, receive, send):
        raise RuntimeError("路由內部錯誤")

    mw = UploadAuthPrecheckMiddleware(failing)
    with pytest.raises(RuntimeError):
        await mw(_request(), _Recorder().receive, _Recorder().send)
    assert mw._reserved_bytes == 0

    gate = _Gate()
    mw = UploadAuthPrecheckMiddleware(gate.inner_app)
    task = asyncio.create_task(mw(_request(), _Recorder().receive, _Recorder().send))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert mw._reserved_bytes == 0


@pytest.mark.usefixtures("threshold")
async def test_量不到剩餘空間時放行並記_error(monkeypatch, caplog):
    """這道檢查壞掉（掛載點斷線、權限）時，不該連帶讓所有上傳失敗。"""

    def broken(path: str) -> int:
        raise OSError("Stale file handle")

    monkeypatch.setattr(upload_disk_guard, "_free_bytes", broken)
    with caplog.at_level(logging.ERROR):
        rec = await _run(_request())

    assert rec.status == 201
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records), "要留下 ERROR 與 traceback"


@pytest.mark.usefixtures("threshold")
async def test_空間不足的_error_每分鐘最多一筆_並記被擋次數(monkeypatch, caplog):
    """持續的上傳嘗試不可刷掉同期其他 log。"""
    _free(monkeypatch, {"et": 0})
    clock = [1000.0]
    monkeypatch.setattr(upload_disk_guard.time, "monotonic", lambda: clock[0])

    with caplog.at_level(logging.ERROR):
        for _ in range(5):
            assert (await _run(_request())).status == 507
        clock[0] += upload_disk_guard._LOG_INTERVAL_SEC
        assert (await _run(_request())).status == 507

    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2, "第一次記、一分鐘內不再記、過了一分鐘再記"
    assert "另擋下 0 次" in errors[0]
    assert "另擋下 4 次" in errors[1], "中間被擋的次數要併入下一筆"


def test_預留上限與_nginx_的_body_上限一致():
    """預留額度取 nginx 的 `client_max_body_size`；只改一邊的話，預留會比實際能寫入的少。"""
    conf = (Path(__file__).resolve().parents[3] / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    sizes = dict(re.findall(r"location ~ \^/api/(dm|et)/[^\n]*\{\s*client_max_body_size (\d+)m;", conf))

    assert int(sizes["et"]) == upload_disk_guard.ET_VIDEO_MAX_BODY_MB
    assert int(sizes["dm"]) == upload_disk_guard.DM_DOCUMENT_MAX_BODY_MB


# ── 量測目錄 ─────────────────────────────────────────────────────────


def test_量的是暫存與兩個存放區(monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", "/data/dm")
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", "/data/et")

    assert upload_disk_guard.upload_dirs() == {"tmp": tempfile.gettempdir(), "dm": "/data/dm", "et": "/data/et"}


def test_真的磁碟_目錄還不存在時量最近的上層目錄(tmp_path):
    """全新部署的存放區在第一次上傳前還沒建立，`shutil.disk_usage` 對不存在的路徑會拋錯。"""
    missing = tmp_path / "not" / "yet" / "created"

    assert upload_disk_guard._free_bytes(str(missing)) > 0
    assert not missing.exists(), "量測不可順手建立目錄"


async def test_真的磁碟_門檻高於剩餘空間就擋(monkeypatch, tmp_path):
    """不經替身，走真的 `shutil.disk_usage`：門檻設成比整顆磁碟還大，必擋；設 1 MB 必放行。"""
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_MIN_FREE_DISK_MB", 10**12)  # 1 EB，任何磁碟都不夠
    assert (await _run(_request())).status == 507

    monkeypatch.setattr(settings, "UPLOAD_MIN_FREE_DISK_MB", 1)
    assert (await _run(_request())).status == 201


def test_預設門檻為_10_GB():
    """測試環境的 conftest 設為 0；正式環境與院內交付版不設時要是 10 GB。"""
    assert type(settings).model_fields["UPLOAD_MIN_FREE_DISK_MB"].default == 10 * 1024
