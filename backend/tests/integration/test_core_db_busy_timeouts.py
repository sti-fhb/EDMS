"""連線池等候逾時（#833 B1）與稽核鎖等鎖逾時（#833 B2）確實生效。

單元測試只驗「例外 → 503」的對應；這裡連真 DB 驗 unit 驗不到的部分：
- 連線池滿時拋出的**確實是** `sqlalchemy.exc.TimeoutError`，而且從 `AsyncSession` 一路冒到請求層時
  沒被包成別的例外——對應寫錯類別，503 永遠不會出現，而 unit 測試照樣全綠
- 稽核鎖的等鎖上限真的到了 PostgreSQL、真的會中止等待，而且**只管這一把鎖**：取到鎖之後
  `lock_timeout` 要還原，同一交易接下來等其他鎖（課程行鎖等）不受影響
"""

import time

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.db import create_app_engine, get_db
from app.dp.audit.repository import _AUDIT_CHAIN_LOCK_KEY, AuditLogRepository

pytestmark = pytest.mark.integration


# ── B1：連線池等候逾時 ────────────────────────────────────────────────────


async def test_連線池滿時等候逾時拋_SQLAlchemy_的_TimeoutError(apply_migrations):
    engine = create_app_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=0.2)
    try:
        async with engine.connect():  # 佔住唯一一條
            started = time.monotonic()
            with pytest.raises(SATimeoutError):
                async with AsyncSession(engine) as session:
                    await session.execute(text("SELECT 1"))
            elapsed = time.monotonic() - started

        # 正向錨點：連線歸還後同一個池照常可用——上面的逾時不是因為連線本身壞了
        async with AsyncSession(engine) as session:
            assert (await session.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await engine.dispose()

    assert elapsed < 1.5, f"應在等候上限附近放棄，實際 {elapsed:.2f}s"


async def test_連線池滿時請求回_503_系統忙碌(apply_migrations, monkeypatch):
    """因果鏈的終點：池滿 → 認證閘第一句查詢拋逾時 → 使用者收到 503，不是 500。

    ⚠️ 以 `debug=False` 重建 middleware：`.env` 設 `DEBUG=true` 時，Starlette 的 `ServerErrorMiddleware`
    直接回堆疊頁、**不呼叫** catch-all handler，本條會在開發機紅、與正式環境（`DEBUG=false`）行為不同。
    """
    from main import app

    monkeypatch.setattr(app, "debug", False)
    monkeypatch.setattr(app, "middleware_stack", None)  # 下一個請求以 debug=False 重建；結束後還原
    engine = create_app_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=0.2)

    async def exhausted_db():
        async with AsyncSession(engine) as session:
            yield session

    token = create_access_token(sub="ZT_POOL833", ttl_minutes=5)
    app.dependency_overrides[get_db] = exhausted_db
    try:
        async with engine.connect():  # 佔住唯一一條
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                r = await client.get("/api/dp/user/me", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()

    assert r.status_code == 503, r.text
    assert r.json() == {"error_code": "COMMON_503", "error_message": "系統忙碌中，請稍後再試"}


# ── B2：稽核鎖等鎖逾時 ────────────────────────────────────────────────────


@pytest.fixture
async def two_connections(apply_migrations):
    """持鎖者與等鎖者各一條**獨立**連線（advisory lock 對同一個 backend 可重入，同一條連線測不出等待）。"""
    engine = create_app_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as holder, engine.connect() as waiter:
            yield holder, waiter
    finally:
        await engine.dispose()


async def _hold_audit_lock(holder) -> None:
    await holder.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_AUDIT_CHAIN_LOCK_KEY))


async def test_稽核鎖等超過上限即放棄(two_connections, monkeypatch):
    monkeypatch.setattr(settings, "DB_AUDIT_LOCK_TIMEOUT_MS", 200)
    holder, waiter = two_connections
    await _hold_audit_lock(holder)

    started = time.monotonic()
    with pytest.raises(DBAPIError) as exc:
        await AuditLogRepository().acquire_chain_lock(AsyncSession(bind=waiter))
    elapsed = time.monotonic() - started

    assert getattr(exc.value.orig, "sqlstate", None) == "55P03", "應為 lock_not_available（lock_timeout）"
    assert elapsed < 1.5, f"應在等鎖上限附近放棄，實際 {elapsed:.2f}s"


async def test_持鎖者放開後照常取得稽核鎖(two_connections, monkeypatch):
    """正向錨點：上限以內放開就取得——上面的放棄不是因為鎖永遠拿不到。"""
    monkeypatch.setattr(settings, "DB_AUDIT_LOCK_TIMEOUT_MS", 5_000)
    holder, waiter = two_connections
    await _hold_audit_lock(holder)
    await holder.rollback()

    await AuditLogRepository().acquire_chain_lock(AsyncSession(bind=waiter))

    held = await waiter.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :k AND pid = pg_backend_pid()"),
        {"k": _AUDIT_CHAIN_LOCK_KEY},
    )
    assert held.scalar() == 1


async def test_取得稽核鎖後還原原本的等鎖上限(two_connections, monkeypatch):
    """只管稽核鎖：取到之後 `lock_timeout` 回到取鎖前的值，同一交易接下來等別的鎖不受 10 秒限制。

    取鎖前先把 session 設成 3s（不是 PostgreSQL 預設的 0），才分得出「還原成原值」與「寫死還原成 0」。
    """
    monkeypatch.setattr(settings, "DB_AUDIT_LOCK_TIMEOUT_MS", 200)
    _, waiter = two_connections
    await waiter.execute(text("SET lock_timeout = '3s'"))
    await waiter.commit()

    await AuditLogRepository().acquire_chain_lock(AsyncSession(bind=waiter))

    assert (await waiter.execute(text("SHOW lock_timeout"))).scalar() == "3s"


async def test_同一交易取兩次稽核鎖後仍還原原值(two_connections, monkeypatch):
    """ET 批次核可等呼叫者在同一交易寫多筆稽核，每筆都會取一次鎖（可重入）；第二次讀到的「原值」必須
    還是取鎖前的值，不能是第一次設下的上限。"""
    monkeypatch.setattr(settings, "DB_AUDIT_LOCK_TIMEOUT_MS", 200)
    _, waiter = two_connections
    await waiter.execute(text("SET lock_timeout = '3s'"))
    await waiter.commit()
    session = AsyncSession(bind=waiter)

    await AuditLogRepository().acquire_chain_lock(session)
    await AuditLogRepository().acquire_chain_lock(session)

    assert (await waiter.execute(text("SHOW lock_timeout"))).scalar() == "3s"
