"""送檔前結束交易、把連線還給連線池（#810 第 3 項）。

FastAPI 0.139 的 `get_db` 要等 response **整個送完**才 commit／close（dependency 在送完後才收尾）。
送檔端點若不先結束交易，下載或看影片的整段期間都佔住一條 DB 連線——連線池只有 15 條。

⚠️ 不用 conftest 的 `db` fixture：它的 engine 是 NullPool，沒有「借出幾條」可以觀察；這裡另建一個
池大小 1 的 engine，直接看 `checkedout()`。
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import create_app_engine, get_db, release_db_before_streaming
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context, get_dm_reviewer_context
from app.dm.detail import router as dm_detail_router
from app.dm.review import router as dm_review_router
from app.et.deps import EtContext, get_et_context
from app.et.learning import router as learning_router
from app.et.learning.video_ticket import issue_video_ticket
from main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def pooled_engine(apply_migrations):
    engine = create_app_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


async def test_送檔前呼叫後連線已歸還連線池(pooled_engine):
    async with AsyncSession(pooled_engine, expire_on_commit=False) as session:
        await session.execute(text("SELECT 1"))
        # 正向錨點：查詢之後確實借著一條——下面的「0」不是因為根本沒借
        assert pooled_engine.pool.checkedout() == 1

        await release_db_before_streaming(session)

        assert pooled_engine.pool.checkedout() == 0


@dataclass(frozen=True)
class _FileEndpoint:
    """一支送檔端點：要打的 URL，與它查檔那一步的 service 方法（換成假的）。"""

    path: str
    #: 測試當下才產生（ET 影片票只有 300 秒效期，模組載入時就簽的話，整套測試跑到這裡可能已過期）
    query: Any
    service: Any
    method: str
    #: 給定暫存檔路徑，回傳該 service 方法原本的回傳形狀
    returns: Any


def _served(path: str) -> SimpleNamespace:
    """DM 的 `FileServe`／`ReviewFile`、ET 的文件內容皆以屬性取用（path／mime／name／inline）。"""
    return SimpleNamespace(path=path, mime="application/pdf", name="f.pdf", inline=False)


_ENDPOINTS = {
    "DM-文件下載": _FileEndpoint(
        "/api/dm/documents/DM-SOP-000001/versions/1/file",
        lambda: "",
        dm_detail_router._service,
        "prepare_file",
        _served,
    ),
    "DM-簽核下載": _FileEndpoint(
        "/api/dm/reviews/1/versions/1/file", lambda: "", dm_review_router._service, "prepare_file", _served
    ),
    "DM-廢止附件": _FileEndpoint(
        "/api/dm/reviews/1/obsolete-file", lambda: "", dm_review_router._service, "prepare_obsolete_file", _served
    ),
    "ET-教材文件": _FileEndpoint(
        "/api/et/materials/1/docs/DM-SOP-000001/file", lambda: "", learning_router._service, "doc_file", _served
    ),
    "ET-影片串流": _FileEndpoint(
        "/api/et/videos/1/file",
        lambda: f"t={issue_video_ticket(user_id='u1', video_id=1)}",
        learning_router._service,
        "video_file_by_ticket",
        lambda path: (path, "v.mp4"),
    ),
}


@pytest.mark.parametrize("name", list(_ENDPOINTS))
async def test_送檔端點傳送檔案內容的期間不佔連線(name, pooled_engine, monkeypatch, tmp_path):
    """端點層級（security review 建議）：送出第一塊檔案內容的當下，已沒有借出任何連線。

    上一條只測 helper；這條走真正的路由與 FastAPI 的 dependency 生命週期（`get_db` 換成池化版，
    行為與正式環境相同）。換成假的只有兩處：
    - 查檔的 service 方法：照樣跑一次真的查詢、真的借出連線，再回一個 1MB 的暫存檔——免得要在 DB
      裡 commit 一整份文件或課程
    - 身分依賴（`get_dm_context` 等）：本條驗的是連線，不是授權
    拿掉 `release_db_before_streaming` 的話，`get_db` 要等整份檔案送完才收尾，此處會是 1。
    """
    endpoint = _ENDPOINTS[name]
    file = tmp_path / "f.bin"
    file.write_bytes(b"\0" * (1024 * 1024))

    async def fake_lookup(db, *args, **kwargs):
        await db.execute(text("SELECT 1"))
        return endpoint.returns(str(file))

    monkeypatch.setattr(endpoint.service, endpoint.method, fake_lookup)

    async def pooled_get_db():
        async with AsyncSession(pooled_engine, expire_on_commit=False, autoflush=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    dm_ctx = DmContext(user_id="u1", roles=frozenset())
    overrides = {
        get_db: pooled_get_db,
        get_dm_context: lambda: dm_ctx,
        get_dm_reviewer_context: lambda: dm_ctx,
        get_operator: lambda: OperatorInfo(user_id="u1"),
        get_et_context: lambda: EtContext(user_id="u1", roles=frozenset()),
    }
    app.dependency_overrides.update(overrides)

    checked_out_at_first_chunk: list[int] = []
    status: list[int] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body" and not checked_out_at_first_chunk:
            checked_out_at_first_chunk.append(pooled_engine.pool.checkedout())

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": endpoint.path,
        "raw_path": endpoint.path.encode(),
        "query_string": endpoint.query().encode(),
        "root_path": "",
        "headers": [(b"host", b"t")],
        "client": ("127.0.0.1", 1),
        "server": ("t", 80),
    }
    try:
        await app(scope, receive, send)
    finally:
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)

    assert status == [200]
    assert checked_out_at_first_chunk == [0], "送檔期間仍佔著 DB 連線"
