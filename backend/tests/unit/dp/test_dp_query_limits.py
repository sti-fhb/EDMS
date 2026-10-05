"""查詢參數長度上限（#513 第 3 項）。

全庫 router 的字串查詢參數只有三處缺 `max_length`——`dm/obsolete_archive` 的 `category` ×2
與 `dp/roles` 的 `keyword`。`keyword` 流向 ILIKE；`category` 為等值比對，超長值無意義但不該進查詢。

授權閘與 DB session 以 `dependency_overrides` 換掉：422 在 handler 本體執行前就發生，
不需要真 DB（`sti-testing.md`：輸入驗證一律寫 unit）。
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import APIRouter
from httpx import ASGITransport

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context
from app.dm.roles.authz import DM_ADMIN
from main import app

pytestmark = pytest.mark.unit

_OBSOLETE_URL = "/api/dm/obsolete-archive/documents"
_ROLES_URL = "/api/dp/roles/DM/assignments"


async def _fake_db() -> AsyncGenerator[None, None]:
    """不連 DB。參數不合法時 handler 本體不執行；合法時會拿它去查而炸開（見下方 fixture 說明）。"""
    yield None


def _assert_validation_passed(resp) -> None:
    """斷言「參數通過了驗證」——這是「界限值放行」那幾條真正要證明的事。

    ⚠️ 不能只寫 `!= 422`：401 / 403 / 404 都會讓它通過，於是**萬一 router 閘的 override 失效**
    （依賴結構改變、工廠換實作…），這幾條會繼續是綠的卻不再鑑別任何事——偏偏那正是最需要它
    出聲的時候。故把兩種「假通過」明確列為失敗：

    - `422` = 被參數驗證擋下，即本條要測的反面
    - `401` = 未通過認證 → router 閘的 override 沒生效，本條已失去意義

    其餘狀態（`500` 撞 stub DB、`403` 服務層自己的越權檢核）都代表請求**已越過參數驗證**，
    即為放行。不寫死某一個碼：兩個端點停下來的位置本就不同
    （obsolete 走到 repository 撞 `None`；roles 先被服務層的越權檢核擋下）。
    """
    assert resp.status_code not in (401, 422), f"預期已通過參數驗證，實得 {resp.status_code}"


@pytest.fixture
def client():
    """綁 app 的 client；授權閘與 DB 皆以 stub 取代。

    `raise_app_exceptions=False` 使 handler 內的例外轉成 500 回應而非拋回測試——否則
    「界限值放行」那幾條會因 stub DB 炸開而 error 而非拿到狀態碼。判定見 `_assert_validation_passed`。
    """
    # ⚠️ **函式層 import**：`app.dp.roles.router` 若在模組層排到 `main` 之前載入，會觸發
    # `app.services` ↔ `app.dp.users` 之間的循環 import（整個測試檔 collection 失敗）。
    # isort 會把它排在 `main` 前面，所以不能放模組層。
    from app.dp.roles.router import router as roles_router

    # 該 router 的閘是 `require_any_module_admin()` **工廠產生的實例**，無法用工廠本身 override
    # （每次呼叫回新物件），須取 router 上實際註冊的 callable。逐一取而非寫死 `[0]`：日後若加
    # 第二個 router-level 依賴，索引會變。不 override 的話依賴解析早於參數驗證 → 先回 401。
    roles_gates = [d.dependency for d in roles_router.dependencies if d.dependency is not None]

    # import 成功後才開始設 override——否則 import 失敗時 fixture 在 yield 前拋錯、
    # teardown 不會執行，已設的 override 會殘留並影響其他測試。
    app.dependency_overrides[get_dm_context] = lambda: DmContext(user_id="u1", roles=frozenset({DM_ADMIN}))
    app.dependency_overrides[get_operator] = lambda: OperatorInfo(user_id="u1")
    app.dependency_overrides[get_db] = _fake_db
    for gate in roles_gates:
        app.dependency_overrides[gate] = lambda: None
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    yield httpx.AsyncClient(transport=transport, base_url="http://t")
    for dep in (get_dm_context, get_operator, get_db, *roles_gates):
        app.dependency_overrides.pop(dep, None)


@pytest.mark.parametrize("url", [_OBSOLETE_URL, f"{_OBSOLETE_URL}/export"])
async def test_已廢止查詢之_category_超過欄位長度回_422(client, url):
    """`category` 對應 `DM_CATEGORY.CATEGORY_CODE` 之 VARCHAR(10)。清單與匯出兩個端點各一。"""
    async with client as c:
        resp = await c.get(url, params={"category": "X" * 11})

    assert resp.status_code == 422


@pytest.mark.parametrize("url", [_OBSOLETE_URL, f"{_OBSOLETE_URL}/export"])
async def test_已廢止查詢之_category_在長度內放行(client, url):
    """上限不可誤擋正常值——界限值 10 須通過驗證。"""
    async with client as c:
        resp = await c.get(url, params={"category": "X" * 10})

    _assert_validation_passed(resp)


async def test_權限指派查詢之_keyword_超過上限回_422(client):
    """`keyword` 流向 ILIKE，上限 255 = `DP_USER.EMAIL` 之 VARCHAR(255)（#513）。

    ⚠️ 這裡**刻意寫死數字、不 import `USER_KEYWORD_MAX_LEN`**：若從實作取值，常數改成多少
    這兩條都會跟著通過，等於沒有把關。寫死才能在有人調整上限時逼他回來看一眼。
    """
    async with client as c:
        resp = await c.get(_ROLES_URL, params={"keyword": "X" * 256})

    assert resp.status_code == 422


async def test_權限指派查詢之_keyword_在上限內放行(client):
    """界限值 255 須通過驗證（同上，數字刻意寫死）。"""
    async with client as c:
        resp = await c.get(_ROLES_URL, params={"keyword": "X" * 255})

    _assert_validation_passed(resp)


def _keyword_max_len(router: APIRouter, route_path: str, param_name: str) -> int | None:
    """取某 router 上某 route 的某 query 參數之 `max_length`（找不到則 AssertionError）。

    ⚠️ 直接問 router 而非 `app.routes`：本版 FastAPI 的 `app.routes` 放的是 `_IncludedRouter`
    惰性包裝物、不是攤平的 `APIRoute`，沿著它找端點會一律落空（而「找不到」若被寫成回 None，
    這條測試就會變成恆真）。故找不到一律 raise，不回 None。
    """
    for route in router.routes:
        if getattr(route, "path", None) != route_path:
            continue
        for field in route.dependant.query_params:
            if field.name == param_name:
                # Pydantic v2：`max_length` 不在 `Query` 物件上，而在 `metadata` 裡的
                # `annotated_types.MaxLen`。沒設上限時 metadata 無該項 → 回 None。
                return next(
                    (m.max_length for m in field.field_info.metadata if hasattr(m, "max_length")),
                    None,
                )
        raise AssertionError(f"{route_path} 上找不到 query 參數 {param_name}")
    raise AssertionError(f"{router} 上找不到 route {route_path}")


def test_三處使用者關鍵字查詢共用同一上限():
    """同一個查詢從三個端點進來，上限必須一致（#513 Security LOW-1）。

    `dp/roles` 的 `keyword` 是**原封不動**交給 `UsersService.list_users`——與 `dp/users` 清單
    是同一個查詢。本次修正前兩者分別是 200 與 255，於是 230 字的關鍵字在人員管理頁搜得到、
    在權限指派頁 422，而兩頁的搜尋語意完全相同。

    改用共用常數後此刻必然一致，**但常數可以再被改回字面值**——這條測試就是為了讓那件事變紅。
    斷言「彼此相等」而非「都等於 255」：數值本身由上面兩條界限測試釘住，此處只管它們不分家。
    """
    # 函式層 import，理由同上方 fixture（模組層會觸發循環 import）。
    from app.dp.roles.router import router as roles_router
    from app.dp.users.router import router as users_router

    roles_len = _keyword_max_len(roles_router, "/api/dp/roles/{module}/assignments", "keyword")
    users_len = _keyword_max_len(users_router, "/api/dp/users", "q")
    invites_len = _keyword_max_len(users_router, "/api/dp/users/invites", "q")

    assert roles_len is not None, "dp/roles 的 keyword 未設 max_length"
    assert roles_len == users_len == invites_len, (
        f"三處上限不一致：roles={roles_len}、users={users_len}、invites={invites_len}。"
        "三者走同一個 UsersService.list_users / list_invites 查詢，上限分家會造成同字串一頁可搜一頁 422。"
    )
