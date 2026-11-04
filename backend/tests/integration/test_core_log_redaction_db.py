"""DB 錯誤主訊息裡的值，以真實 PostgreSQL + asyncpg 產生的例外驗遮罩（#905 B10）。

單元測試用手刻的訊息；本檔釘住**真實格式**——asyncpg 或 PostgreSQL 升級改了訊息長相時，
這裡會先紅，而不是正式環境的 log 悄悄開始帶值。

⚠️ 每條都先斷言原始例外確實帶值，否則格式一變、值根本不在訊息裡時，「遮掉了」會是空的斷言。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.log_redaction import format_exception_for_log

pytestmark = pytest.mark.integration

_ID = "A123456789"


async def _raise_from_db(sql: str) -> DBAPIError:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(text(sql), {"v": _ID})
    finally:
        await engine.dispose()
    return caught.value


@pytest.mark.parametrize(
    ("sql", "kept"),
    [
        # PostgreSQL 伺服端解析失敗：值在主訊息
        ("SELECT CAST(CAST(:v AS text) AS integer)", "invalid input syntax for type integer"),
        # asyncpg 用戶端編碼參數失敗：值在 DataError 與根因 ValueError
        ("SELECT CAST(:v AS uuid)", "invalid input for query argument $1"),
    ],
)
async def test_real_db_error_value_masked(sql, kept):
    exc = await _raise_from_db(sql)
    assert _ID in str(exc).split("[SQL:")[0]  # 基準：主訊息確實帶值（[parameters:] 那份不算）

    out = format_exception_for_log(exc)
    assert _ID not in out
    # 只比對每層例外的標頭行：堆疊的原始碼行可能含相同字面，會讓正向斷言變成空的
    headers = "\n".join(line for line in out.splitlines() if not line.startswith(" "))
    assert kept in headers
