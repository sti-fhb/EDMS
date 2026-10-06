"""`create_app_engine` 的連線設定驗收：伺服端日期運算一律以台灣時間為界（#483 第 3 項）。

`func.date()` 等**伺服端**運算吃 PostgreSQL session 的 TimeZone。engine 未顯式指定時吃 DB server
預設——開發機為 `Asia/Taipei` 故看不出異狀，但 Cloud SQL 預設 `UTC`，屆時台灣時間早上發布的
文件會被歸到前一天，DM01 / DM03 / DM05 的日期篩選同時失準。

⚠️ **每條測試都先斷言「同一條 SQL 在 UTC session 下回前一天」**，再斷言經 `create_app_engine`
的連線回當天。少了前一句，本檔在 server 預設即為 `Asia/Taipei` 的機器上，**把修法拔掉也照樣
全過**——那正是這個缺陷原本藏身的地方（見 `app/core/db.py` 的註解）。
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import create_app_engine

pytestmark = pytest.mark.integration

# 台灣時間 2026-10-01 07:00 ＝ UTC 2026-09-30 23:00：兩個時區分屬不同日期，故可用來驗日界。
_MORNING = "SELECT date(TIMESTAMPTZ '2026-10-01 07:00:00+08')"


def _engine_with_tz(tz: str):
    """以指定 session timezone 建測試用 engine（模擬不同部署環境的 DB server 預設）。"""
    return create_async_engine(
        settings.DATABASE_URL, poolclass=NullPool, connect_args={"server_settings": {"timezone": tz}}
    )


async def test_日期運算在_utc_session_下會落到前一天():
    """對照組：證明 `date()` 確實對 session timezone 敏感，下一條斷言才不是空的。"""
    engine = _engine_with_tz("UTC")
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text(_MORNING))).scalar() == date(2026, 9, 30)
    finally:
        await engine.dispose()


async def test_app_engine_將日界釘在台灣時間():
    """`create_app_engine` 建立的連線，不論 DB server 預設為何，日界皆為台灣時間。"""
    engine = create_app_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text(_MORNING))).scalar() == date(2026, 10, 1)
            assert (await conn.execute(text("SHOW TimeZone"))).scalar() == "Asia/Taipei"
    finally:
        await engine.dispose()


async def test_timestamptz_回傳給_python_仍為_utc_aware():
    """設定 session timezone **不得**改變 API 回應格式。

    asyncpg 以 binary protocol 解碼 `timestamptz`，與 session TimeZone 無關；此處釘住該性質，
    避免日後有人改用會影響回傳值的做法（如 `SET TIME ZONE` 配合文字輸出）而**靜默**改掉所有
    API 的時間序列化格式。
    """
    engine = create_app_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            value = (await conn.execute(text("SELECT TIMESTAMPTZ '2026-10-01 07:00:00+08'"))).scalar()
    finally:
        await engine.dispose()

    assert value == datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc)
    assert value.tzinfo == timezone.utc
