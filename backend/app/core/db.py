from collections.abc import AsyncGenerator, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 伺服端日期運算（`func.date()` 等）的時區基準。全系統以台灣時間切日，不吃 DB server 預設。
_SESSION_TIMEZONE = "Asia/Taipei"


def _build_connect_args(connect_args: Mapping[str, Any] | None) -> dict[str, Any]:
    """把全系統 session 設定併入 `connect_args`；呼叫端同名的 `server_settings` 鍵優先。

    ⚠️ 抽成純函式**是為了讓它測得到**。若只在 `create_app_engine` 內就地合併，唯一的驗證方式
    是連上 DB 看 `SHOW TimeZone`——而那在 server 預設本來就是 `Asia/Taipei` 的機器上（本專案
    開發機即是），**把設定整段拔掉也照樣會過**，等於沒有迴歸保護。實測確認過此事。
    見 `tests/unit/test_core_db.py`。

    Args:
        connect_args: 呼叫端傳入的 `connect_args`，可為 None。

    Returns:
        合併後的新 dict（不就地修改傳入值）。
    """
    merged: dict[str, Any] = dict(connect_args or {})
    merged["server_settings"] = {"timezone": _SESSION_TIMEZONE, **merged.get("server_settings", {})}
    return merged


def create_app_engine(url: str, **kwargs: Any) -> AsyncEngine:
    """建立 async engine，一律套用全系統連線設定。

    **所有 engine 都要經由本函式建立**（含測試用的），否則該連線的日界會回去吃 DB server 預設，
    而兩者差異只在某些部署環境才看得出來——見下方說明。

    ## 為何要釘住 session timezone（#483）

    `published_date` 等欄位為 `TIMESTAMPTZ`，而 `func.date(...)`（日期區間篩選用）是在**伺服端**
    依 session 的 `TimeZone` 轉換後取日期。不指定就吃 DB server 預設：開發機為 `Asia/Taipei`
    故一切正常，但 Cloud SQL 預設 `UTC`，屆時台灣時間早上發布的文件會被算成前一天，
    使用者篩當天就找不到（DM01 / DM03 / DM05 三處日期篩選同時失準，且沒有任何測試會紅）。

    這也是 `app/core/utils.py::utcnow` 宣告的全系統基準「不依賴 OS / DB server / Docker 的
    timezone 設定」原本未被落實的一角。

    ## 不影響 API 回應格式

    asyncpg 以 binary protocol 解碼 `timestamptz`，回給 Python 的恆為 UTC aware datetime，
    與 session TimeZone 無關；本設定只改變**伺服端計算**。
    `tests/integration/test_core_db_timezone.py` 釘住此性質。

    Args:
        url: 資料庫連線字串。
        **kwargs: 其餘 `create_async_engine` 參數；`connect_args` 會與本函式的設定合併
            （同名的 `server_settings` 鍵以呼叫端為準）。

    Returns:
        套用全系統連線設定的 `AsyncEngine`。
    """
    return create_async_engine(url, connect_args=_build_connect_args(kwargs.pop("connect_args", None)), **kwargs)


engine = create_app_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依賴注入用的資料庫 session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
