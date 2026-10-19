"""`main.py` 的 `DataError` 兜底處理器（#697）。

## 為何需要兜底，而不是只靠欄位級驗證

PostgreSQL 會拒絕兩類「格式上合法、值域上不合法」的輸入——超過 `String(N)` 的字串
（`StringDataRightTruncation`）與含 `\\x00` 的文字（`CharacterNotInRepertoireError`，實測
連純 `SELECT $1::text` 綁定都會拋，不必寫入）。兩者都是 `DataError` 的子類。

在本處理器之前，全庫（`app/` + `main.py`）**零個** SQLAlchemy 例外處理器，於是這類例外會
落到最後的 `Exception` catch-all、冒成 500。這個根因已被六份不同的 docstring 各自描述、
各自以欄位級防護繞過，但沒有人處理它本身——而**漏掉的那一欄不會有任何測試變紅**。

## ⛔ 本檔同時守住「不可連 IntegrityError 一起收」

`app/dm/editor/service.py` 用 `IntegrityError` 做兩件業務判斷：DOC_ID 配號的 SAVEPOINT
重試、以及「每人每文件一份進行中版本」的 `DM_DOC_009`。把它一併轉成通用 422 會把那兩處
的語意吃掉，而且**不會有任何現有測試變紅**（它們斷言的是 409 / 重試成功，不是例外型別）。
"""

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from starlette.requests import Request

from main import app, data_error_handler

pytestmark = pytest.mark.unit


def _data_error() -> DataError:
    return DataError("INSERT INTO x", {}, Exception("value too long for type character varying(200)"))


def _request() -> Request:
    """最小 ASGI scope——handler 會記 `request.method` / `request.url.path`。"""
    return Request({"type": "http", "method": "POST", "path": "/api/dm/documents", "headers": []})


async def test_data_error_轉成_422_而非_500():
    resp = await data_error_handler(_request(), _data_error())
    assert resp.status_code == 422


async def test_回應不含_SQL_與綁定參數():
    """錯誤回應只給通用訊息——SQL 與使用者輸入都不得外流。

    `DataError` 的 `str()` 含 statement 與 params，直接回傳就是把輸入值（可能是個資）
    與 schema 一起吐給呼叫端。
    """
    resp = await data_error_handler(_request(), _data_error())
    body = resp.body.decode()

    assert "COMMON_422" in body
    assert "INSERT INTO" not in body, "不得洩漏 SQL"
    assert "character varying" not in body, "不得洩漏欄位型別"


def test_handler_已註冊於_app():
    """直接呼叫函式會通過，但沒註冊到 app 上就等於沒有這道防線。"""
    assert DataError in app.exception_handlers, "DataError handler 未註冊"


def test_不可攔截_IntegrityError():
    """⛔ `IntegrityError` 是 `dm/editor/service` 的並發後盾，收掉會吃掉業務語意。

    兩者在 SQLAlchemy 是 `DatabaseError` 底下的兄弟類別、互不繼承——本條把這個前提釘住，
    日後若有人改成註冊更上層的 `DatabaseError` / `DBAPIError`，這裡會紅。
    """
    assert not issubclass(IntegrityError, DataError)
    assert not issubclass(DataError, IntegrityError)
    assert IntegrityError not in app.exception_handlers
    # 也不可經由父類別被間接攔截
    for registered in app.exception_handlers:
        if isinstance(registered, type) and issubclass(IntegrityError, registered):
            assert registered is Exception, f"IntegrityError 會被 {registered.__name__} 的 handler 攔走"
