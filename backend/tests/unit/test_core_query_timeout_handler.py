"""`main.py` 的查詢逾時處理器（#810 第 2 項）。

查詢超過 `statement_timeout`（`DB_STATEMENT_TIMEOUT_MS`）時，PostgreSQL 以 SQLSTATE 57014 中止它，
SQLAlchemy 包成 `DBAPIError`——**不是** `DataError`，原本會落到最後的 `Exception` catch-all：
回 500「Internal Server Error」並以 ERROR 印出堆疊。使用者看不出是系統忙碌，系統真的忙時 log 被刷滿
（code review HIGH）。

## ⛔ 只收 57014，其餘照舊

同屬 `DBAPIError` 的連線錯誤等仍回原本的 500——那些不是「忙」，回 503 叫使用者稍後再試是誤導。
判斷寫在 catch-all（`unhandled_exception_handler`）的最前面，**不另外註冊 `DBAPIError` 處理器**：
那會連 `IntegrityError` 一起攔走，`test_core_data_error_handler.py` 的 `test_不可攔截_IntegrityError`
明文禁止（#697）。
"""

import logging

import pytest
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from main import unhandled_exception_handler

pytestmark = pytest.mark.unit


class _PgError(Exception):
    """模擬 asyncpg 轉換後的 DBAPI 例外：帶 `sqlstate`。"""

    def __init__(self, sqlstate: str) -> None:
        super().__init__("canceling statement due to statement timeout")
        self.sqlstate = sqlstate


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/dp/audit/logs/export", "headers": []})


async def test_查詢逾時回_503_系統忙碌(caplog):
    exc = DBAPIError("SELECT ...", {}, _PgError("57014"))

    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), exc)

    assert resp.status_code == 503
    assert resp.body.decode() == '{"error_code":"COMMON_503","error_message":"系統忙碌中，請稍後再試"}'
    # 預期中的忙碌，不是程式錯誤：記 WARNING，不記 ERROR
    assert [r.levelno for r in caplog.records if r.name == "main"] == [logging.WARNING]


async def test_非逾時的資料庫錯誤照舊回_500(caplog):
    """對照：其他 SQLSTATE（例如連線中斷 08006）回應與改前相同——500、記 ERROR。"""
    exc = DBAPIError("SELECT ...", {}, _PgError("08006"))

    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), exc)

    assert resp.status_code == 500
    assert '"error_code":"COMMON_500"' in resp.body.decode()
    assert logging.ERROR in [r.levelno for r in caplog.records if r.name == "main"]
