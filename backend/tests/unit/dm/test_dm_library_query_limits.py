"""文件庫查詢參數的長度上限（#483 第 4 項）。

`keyword` / `author` 原本就有上限，`tag_ids` / `category` / `func_code` 沒有——`tag_id.in_(...)`
的綁定參數有 asyncpg 32767 上限，已認證使用者塞大量值即可把端點打成 500。

存取閘（`get_dm_context`）與 DB session 以 `dependency_overrides` 換掉：本檔只驗參數驗證，
422 在 handler 本體執行前就發生，故不需要真 DB，依 `sti-testing.md`「輸入驗證一律寫 unit」。
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.core.db import get_db
from app.dm.deps import DmContext, get_dm_context
from app.dm.roles.authz import DM_VIEWER
from main import app

pytestmark = pytest.mark.unit

_URL = "/api/dm/library/documents"


async def _fake_db() -> AsyncGenerator[None, None]:
    """不連 DB。參數**不合法**時 handler 本體不執行，用不到這個值；合法時則會拿它去查而炸開。"""
    yield None


@pytest.fixture
def client():
    """綁 app 的 client；存取閘與 DB 皆以 stub 取代。

    `raise_app_exceptions=False` 使 handler 內的例外轉成 500 回應而非拋回測試——「參數合法」
    的那幾條靠的正是這點：**請求能走到 handler 並在 stub DB 上炸開，本身就證明驗證放行了**，
    所以斷言寫成「不是 422」。少了這組，把上限設成 1 也能讓 422 那幾條全過。
    """
    app.dependency_overrides[get_dm_context] = lambda: DmContext(user_id="u1", roles=frozenset({DM_VIEWER}))
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    yield httpx.AsyncClient(transport=transport, base_url="http://t")
    app.dependency_overrides.pop(get_dm_context, None)
    app.dependency_overrides.pop(get_db, None)


async def test_tag_ids_超過上限回_422(client):
    """超量 tag_ids 在進到 SQL 之前就被擋下（否則撞 asyncpg 參數上限 → 500）。"""
    async with client as c:
        resp = await c.get(_URL, params={"tag_ids": list(range(51))})

    assert resp.status_code == 422


async def test_tag_ids_在上限內放行(client):
    """上限本身不可誤擋正常用量——50 筆仍須通過驗證（遠高於實際標籤總數）。

    id 自 1 起算：`TAG_ID` 由 1 開始，0 已由值域檢核擋下（見 `test_tag_id_非正整數回_422`）。
    """
    async with client as c:
        resp = await c.get(_URL, params={"tag_ids": list(range(1, 51))})

    assert resp.status_code != 422


@pytest.mark.parametrize("value", [2**63, 10**30])
async def test_tag_id_超出_int64_回_422(client, value):
    """限制陣列長度還不夠——元素值域也要界住。

    `TAG_ID` 是 BIGINT，但 Pydantic 的 `int` 是任意精度：超出 int64 的值會通過驗證、一路走到
    asyncpg 編碼期才炸 `DataError`，無人攔截 → 500 + 一筆 ERROR 堆疊。任一 DM 角色都打得出來，
    成本極低且可無限重複，足以淹掉真正的 500（#483 security review LOW-1）。
    """
    async with client as c:
        resp = await c.get(_URL, params={"tag_ids": [value]})

    assert resp.status_code == 422


async def test_tag_id_非正整數回_422(client):
    """`TAG_ID` 由 1 起跳，0 與負數不可能命中任何標籤，擋在驗證層而非送進查詢。"""
    async with client as c:
        resp = await c.get(_URL, params={"tag_ids": [0]})

    assert resp.status_code == 422


async def test_合法_tag_id_放行(client):
    """值域上限不可誤擋正常 id（界限值 int64 max 本身仍須通過）。"""
    async with client as c:
        resp = await c.get(_URL, params={"tag_ids": [1, 2**63 - 1]})

    assert resp.status_code != 422


@pytest.mark.parametrize("field", ["category", "func_code"])
async def test_代碼類參數超過欄位長度回_422(client, field):
    """`category` / `func_code` 對應 VARCHAR(10)，超長無意義且不該進查詢。"""
    async with client as c:
        resp = await c.get(_URL, params={field: "X" * 11})

    assert resp.status_code == 422


@pytest.mark.parametrize("field", ["category", "func_code"])
async def test_代碼類參數在長度內放行(client, field):
    async with client as c:
        resp = await c.get(_URL, params={field: "X" * 10})

    assert resp.status_code != 422
