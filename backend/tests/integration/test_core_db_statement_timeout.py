"""查詢逾時確實生效（#810 第 2 項）。

單元測試只驗「設定有組進 connect_args」；這裡連真 DB 驗兩件 unit 驗不到的事：
- 設定值真的到了 PostgreSQL（`pg_settings` 的 `statement_timeout`）——asyncpg 若不認得這個參數或格式不對，
  只有連線時才會知道
- 超時的查詢真的被中止，而且中止得夠快（不是跑完才報錯）

⚠️ 開發機的 PostgreSQL server 預設 `statement_timeout = 0`（不限），所以第一條讀到的非零值只可能來自
本專案的設定，不會像時區那樣被 server 預設值蓋過去（見 `tests/unit/test_core_db.py` 開頭）。
"""

import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import create_app_engine

pytestmark = pytest.mark.integration


async def test_連線帶上設定的查詢逾時(apply_migrations):
    """以 `pg_settings.setting`（毫秒的純數字）比對設定值——`SHOW` 會格式化成 `1min`，本機 .env 改了
    值就對不上（review LOW）。"""
    engine = create_app_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"))
            assert row.scalar() == str(settings.DB_STATEMENT_TIMEOUT_MS)
    finally:
        await engine.dispose()


async def test_超過逾時的查詢被中止(apply_migrations):
    """以 200ms 的逾時跑 2 秒的 `pg_sleep`：應在逾時附近被中止（SQLSTATE 57014），不是等 2 秒跑完。"""
    engine = create_app_engine(
        settings.DATABASE_URL, poolclass=NullPool, connect_args={"server_settings": {"statement_timeout": "200"}}
    )
    try:
        async with engine.connect() as conn:
            # 正向錨點：逾時以內的查詢照常完成——下面的中止不是因為連線本身就壞了
            await conn.execute(text("SELECT pg_sleep(0.05)"))

            started = time.monotonic()
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(text("SELECT pg_sleep(2)"))
            elapsed = time.monotonic() - started
    finally:
        await engine.dispose()

    assert getattr(exc.value.orig, "sqlstate", None) == "57014", "應為 query_canceled（statement timeout）"
    assert elapsed < 1.5, f"應在逾時附近中止，實際 {elapsed:.2f}s"
