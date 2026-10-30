"""`main.py` 的查詢逾時處理器（#810 第 2 項）。

查詢超過 `statement_timeout`（`DB_STATEMENT_TIMEOUT_MS`）時，PostgreSQL 以 SQLSTATE 57014 中止它，
SQLAlchemy 包成 `DBAPIError`——**不是** `DataError`，原本會落到最後的 `Exception` catch-all：
回 500「Internal Server Error」並以 ERROR 印出堆疊。使用者看不出是系統忙碌，系統真的忙時 log 被刷滿
（code review HIGH）。

#833 起另收兩種「忙碌」：等稽核鎖逾時（55P03，B2）、連線池等候逾時（`sqlalchemy.exc.TimeoutError`，B1）。

## ⛔ 只收這三種，其餘照舊

同屬 `DBAPIError` 的連線錯誤等仍回原本的 500——那些不是「忙」，回 503 叫使用者稍後再試是誤導。
判斷寫在 catch-all（`unhandled_exception_handler`）的最前面，**不另外註冊 `DBAPIError` 處理器**：
那會連 `IntegrityError` 一起攔走，`test_core_data_error_handler.py` 的 `test_不可攔截_IntegrityError`
明文禁止（#697）。
"""

import logging

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SATimeoutError
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


async def test_等鎖逾時回_503_系統忙碌(caplog):
    """稽核鎖等超過 `DB_AUDIT_LOCK_TIMEOUT_MS`，PostgreSQL 以 55P03（lock_not_available）中止（#833 B2）。"""
    exc = DBAPIError("SELECT pg_advisory_xact_lock(...)", {}, _PgError("55P03"))

    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), exc)

    assert resp.status_code == 503
    assert resp.body.decode() == '{"error_code":"COMMON_503","error_message":"系統忙碌中，請稍後再試"}'
    assert [r.levelno for r in caplog.records if r.name == "main"] == [logging.WARNING]


async def test_連線池等候逾時回_503_系統忙碌(caplog):
    """連線池滿、等超過 `DB_POOL_TIMEOUT` 時 SQLAlchemy 拋 `sqlalchemy.exc.TimeoutError`（#833 B1）。

    它**不是** `DBAPIError`（還沒拿到連線，沒有 DBAPI 例外可包），所以要另外判斷。
    """
    exc = SATimeoutError("QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 10.00")

    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), exc)

    assert resp.status_code == 503
    assert resp.body.decode() == '{"error_code":"COMMON_503","error_message":"系統忙碌中，請稍後再試"}'
    assert [r.levelno for r in caplog.records if r.name == "main"] == [logging.WARNING]


async def test_Python_內建的_TimeoutError_照舊回_500(caplog):
    """對照：只認 SQLAlchemy 的連線池逾時。內建 `TimeoutError`（例如呼叫外部服務逾時）不是 DB 忙碌。"""
    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), TimeoutError("smtp"))

    assert resp.status_code == 500
    assert logging.ERROR in [r.levelno for r in caplog.records if r.name == "main"]


async def test_非逾時的資料庫錯誤照舊回_500(caplog):
    """對照：其他 SQLSTATE（例如連線中斷 08006）回應與改前相同——500、記 ERROR。"""
    exc = DBAPIError("SELECT ...", {}, _PgError("08006"))

    with caplog.at_level(logging.WARNING, logger="main"):
        resp = await unhandled_exception_handler(_request(), exc)

    assert resp.status_code == 500
    assert '"error_code":"COMMON_500"' in resp.body.decode()
    assert logging.ERROR in [r.levelno for r in caplog.records if r.name == "main"]
