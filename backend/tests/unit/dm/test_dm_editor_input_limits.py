"""DM 編輯／廢止端點的寫入欄位邊界（#697 + #500）。

盤點後發現：`backend/app/dm` 的 9 個寫入端點中，**只有退回原因**（`RejectReq.reason`）有長度
上限；其餘 `max_length` 全是查詢參數（#483 / #513 補的）。本檔守住編輯器三個端點與廢止端點
的輸入邊界。

## 三類缺陷，形狀不同

**① 越界回 500**：`doc_name`(200) / `version_no`(20) / `assigned_reviewer`(20)。
DB 欄位是 `String(N)` 而應用層不檢核 ⇒ 超長值走到 INSERT 才撞 asyncpg
`StringDataRightTruncation`；`main.py` 沒有 `DataError` 的處理器，落到最後的
catch-all ⇒ **500**，使用者只看到「伺服器處理失敗」。

**② 無上限 `Text`**：`change_summary`(1000) / 廢止 `reason`(500)。
欄位存得下，但兩者都會原樣進入信件內文與永久記錄。

**③ 陣列無界**（#500）：`audience_unit_ids` / `audience_role_ids` / `retrieval_ids`。
長度擋查詢成本放大，值域擋「超出 int64 在 asyncpg 編碼期」的未攔截 500。

## 為何是 unit

`sti-testing.md` 明列「輸入驗證（422）一律寫 unit，禁止寫成 integration」。422 在 handler
本體執行前就發生，不需要真 DB。手法照抄 `test_dm_library_query_limits.py`（#483）：存取閘、
`get_operator`、DB session 全以 `dependency_overrides` 換掉，並以
`raise_app_exceptions=False` 讓「合法輸入」那幾條能斷言 `!= 422`——**請求走進 handler 並在
stub DB 上炸開，本身就證明驗證放行了**。少了這組，把上限設成 1 也會讓 422 那幾條全過。

## ⚠️ 兩個實作陷阱，各有一條測試盯著

1. **存草稿允許空值**：`editor/service` docstring 明載「存草稿不卡必填（US5）：名稱 / 版號 /
   摘要 / 檔案皆可空」。`core.schema_types.SAFE_SINGLE_LINE_PATTERN` 是 `^[^…]+$`，`+` 要求
   至少一字元 ⇒ 直接套用會讓存草稿一律 422。見 `test_存草稿_空名稱空版號空摘要仍放行`。
2. **`Form()` 沒有 `strip_whitespace`**：DM 的 `.strip()` 在 service 層、發生在驗證之後，
   故改用 `BeforeValidator` 先 strip 再驗（已實測 `BeforeValidator` 先於 `Form()` 約束執行）。
   見 `test_尾端換行被_strip_後放行_不是_422`。
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context
from app.dm.roles.authz import DM_EDITOR
from main import app

pytestmark = pytest.mark.unit

_CREATE = "/api/dm/documents"
_ADD_VERSION = "/api/dm/documents/DM-SOP-000001/versions"
_UPDATE_DRAFT = "/api/dm/documents/DM-SOP-000001/versions/1"
_OBSOLETE = "/api/dm/documents/DM-SOP-000001/obsolete"


async def _fake_db() -> AsyncGenerator[None, None]:
    """不連 DB。輸入不合法時 handler 本體不執行；合法時則會拿它去查而炸開。"""
    yield None


@pytest.fixture
def client():
    app.dependency_overrides[get_dm_context] = lambda: DmContext(user_id="u1", roles=frozenset({DM_EDITOR}))
    app.dependency_overrides[get_operator] = lambda: OperatorInfo(user_id="u1")
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    yield httpx.AsyncClient(transport=transport, base_url="http://t")
    for dep in (get_dm_context, get_operator, get_db):
        app.dependency_overrides.pop(dep, None)


def _base() -> dict:
    """新增端點的最小合法表單（`category_code` 為結構必填）。"""
    return {"category_code": "SOP"}


# ── 類 1：越界回 500 的三個欄位（本 issue 的核心缺陷）────────────────


@pytest.mark.parametrize(
    ("field", "limit"),
    [("doc_name", 200), ("version_no", 20), ("assigned_reviewer", 20)],
)
async def test_新增_身份欄超過_DB_欄位長度回_422_而非_500(client, field, limit):
    """`DM_DOC.DOC_NAME` / `VERSION_NO` / `ASSIGNED_REVIEWER` 皆為 `String(N)`。

    不在應用層擋的話，超長值走到 INSERT 才被 DB 拒絕，冒成未處理的 500——
    與 `et/material/storage.ensure_file_name_acceptable` 的 docstring 所述、
    以及 #202 修過的三個「越界回 500 而非 4xx」是同一類。
    """
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: "x" * (limit + 1)})

    assert resp.status_code == 422, f"{field} 超過 {limit} 字必須在驗證層擋下"


@pytest.mark.parametrize(
    ("field", "limit"),
    [("doc_name", 200), ("version_no", 20), ("assigned_reviewer", 20)],
)
async def test_新增_身份欄剛好等於上限時放行(client, field, limit):
    """上限不可誤擋界內值——只測「超限 422」的話，把上限設成 1 也會全過。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: "x" * limit})

    assert resp.status_code != 422, f"{field} 剛好 {limit} 字不該被擋"


@pytest.mark.parametrize("field", ["doc_name", "version_no"])
async def test_新增_身份欄含換行回_422(client, field):
    """`DOC_NAME` 會原樣進入 `DOC_PUBLISH` 通知內文，而 `_BODY_TRANS` 刻意保留 LF
    （為了多行退回原因）⇒ 撰寫者可在文件名稱內嵌換行，於發布信偽造額外行。
    收件人是該文件的全體可見對象。沿用 `core.schema_types.SAFE_SINGLE_LINE_PATTERN`。
    """
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: "正常\n偽造的一行"})

    assert resp.status_code == 422


async def test_變更摘要允許換行(client):
    """對照組：摘要本來就該能多行，不可把單行約束誤套到它身上。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), "change_summary": "第一行\n第二行"})

    assert resp.status_code != 422


# ── 陷阱 1：存草稿允許空值 ──────────────────────────────────────


async def test_存草稿_空名稱空版號空摘要仍放行(client):
    """🔴 `SAFE_SINGLE_LINE_PATTERN` 的 `+` 要求至少一字元，直接套用會讓存草稿一律 422。

    `editor/service.create_document` 的 docstring：「存草稿不卡必填（US5）：名稱 / 版號 /
    摘要 / 檔案皆可空，送簽時才完整檢核」。症狀會是「新增文件按存草稿就壞掉」，
    而且只有實際點過才看得到。
    """
    async with client as c:
        resp = await c.post(
            _CREATE,
            data={**_base(), "doc_name": "", "version_no": "", "change_summary": "", "assigned_reviewer": ""},
        )

    assert resp.status_code != 422, "存草稿的空值被擋下了——陷阱 1"


# ── 陷阱 2：Form() 不會先 strip ────────────────────────────────


async def test_尾端換行被_strip_後放行_不是_422(client):
    """`Form()` 沒有 `strip_whitespace`，DM 的 `.strip()` 在 service 層、發生在驗證之後。

    直接掛 `pattern` 會把今天被靜默 strip 掉的尾端換行變成 422（行為退化）。
    改以 `BeforeValidator` 先 strip 再驗——已實測 `BeforeValidator` 先於 `Form()` 約束執行。
    """
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), "doc_name": "  正常名稱  \n"})

    assert resp.status_code != 422, "尾端空白 / 換行應被 strip 掉而非判為不合法"


async def test_strip_後剛好等於上限時放行(client):
    """長度須以 strip **後**的值計算，否則「200 字 + 尾端一個空白」會被誤判超限。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), "doc_name": "x" * 200 + "   "})

    assert resp.status_code != 422


# ── 類 2：無上限 Text ──────────────────────────────────────────


async def test_變更摘要超過上限回_422(client):
    """`CHANGE_SUMMARY` 是無界 `Text`，但它會整段進入 `DOC_PUBLISH` 信件內文。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), "change_summary": "摘" * 1001})

    assert resp.status_code == 422


async def test_變更摘要剛好上限放行(client):
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), "change_summary": "摘" * 1000})

    assert resp.status_code != 422


async def test_廢止申請原因超過上限回_422(client):
    """廢止原因上限 500（裁示 2026-10-17）：長篇理由改用廢止申請的單檔附件。

    它會寫入 `DM_CHANGE_LOG.NOTE`（亦為無界 `Text`）與廢止相關通知。
    """
    async with client as c:
        resp = await c.post(_OBSOLETE, data={"reason": "原" * 501, "reviewer_id": "rev1"})

    assert resp.status_code == 422


async def test_廢止申請原因剛好上限放行(client):
    async with client as c:
        resp = await c.post(_OBSOLETE, data={"reason": "原" * 500, "reviewer_id": "rev1"})

    assert resp.status_code != 422


# ── 其餘兩個編輯端點：同一組欄位，不可只改新增那支 ────────────────


@pytest.mark.parametrize("url", [_ADD_VERSION, _UPDATE_DRAFT])
async def test_加版與續編的版號同樣受限(client, url):
    """三個端點共用同一組 Form 欄位，漏改其中一支不會有別的測試變紅。"""
    method = httpx.AsyncClient.post if url == _ADD_VERSION else httpx.AsyncClient.put
    async with client as c:
        resp = await method(c, url, data={"version_no": "v" * 21})

    assert resp.status_code == 422


async def test_續編的文件名稱同樣受限(client):
    """續編的 `doc_name` 是 `str | None = None`（與新增的 `str = ""` 形態不同），易漏改。"""
    async with client as c:
        resp = await c.put(_UPDATE_DRAFT, data={"doc_name": "x" * 201})

    assert resp.status_code == 422


# ── 類 3：三個 Form 陣列（#500）──────────────────────────────────

_ARRAYS = ["audience_unit_ids", "audience_role_ids", "retrieval_ids"]


@pytest.mark.parametrize("field", _ARRAYS)
async def test_標籤陣列超過長度上限回_422(client, field):
    """Starlette 的 `max_fields = 1000` 撐得住，但 1000 個元素的 `IN` 清單 + 一次寫 1000 筆
    標籤關聯遠超業務意圖（種子只有 9 個檢索標籤）。照抄 DM01（#483 / PR #494）的 50。
    """
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: [str(i) for i in range(1, 52)]})

    assert resp.status_code == 422


@pytest.mark.parametrize("field", _ARRAYS)
async def test_標籤陣列在長度內放行(client, field):
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: [str(i) for i in range(1, 51)]})

    assert resp.status_code != 422


@pytest.mark.parametrize("field", _ARRAYS)
@pytest.mark.parametrize("value", [2**63, 10**30])
async def test_標籤_id_超出_int64_回_422(client, field, value):
    """⚠️ 只限長度不夠：`list[int]` 在 Pydantic 是任意精度，超出 int64 的值會通過驗證、
    到 asyncpg 編碼期才拋 `DataError`，成為未攔截的 500（#483 已連 DB 實測重現）。
    """
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: [str(value)]})

    assert resp.status_code == 422


@pytest.mark.parametrize("field", _ARRAYS)
async def test_標籤_id_非正整數回_422(client, field):
    """`TAG_ID` 由 1 起跳，0 與負數不可能命中任何標籤。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: ["0"]})

    assert resp.status_code == 422


@pytest.mark.parametrize("field", _ARRAYS)
async def test_合法標籤_id_放行(client, field):
    """界限值 int64 max 本身仍須通過。"""
    async with client as c:
        resp = await c.post(_CREATE, data={**_base(), field: ["1", str(2**63 - 1)]})

    assert resp.status_code != 422
