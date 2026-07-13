"""整合測試共用 fixtures（EDMS 精簡版，對齊 TBMS 策略）。

- apply_migrations：session 開始前確保測試 DB 存在、DROP SCHEMA 清乾淨、
  以子程序執行 alembic upgrade head；結束後清理（xdist worker 庫整個 DROP）。
- test_engine：NullPool，不維持連線池，避免跨 test 狀態殘留。
- db：每個 test 取得獨立連線，結束後 rollback，不污染資料庫。

DB 維護（建/刪庫、DROP SCHEMA）以 psql 子程序執行，需 psql 在 PATH
（本機從 PostgreSQL 安裝目錄加入 PATH；GitHub-hosted ubuntu runner 已內建）。
alembic 以子程序執行，避免與 pytest-asyncio 的 session event loop 衝突。
"""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# alembic.ini 位於 backend/ 目錄，使用絕對路徑避免工作目錄假設
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _conn_params() -> dict[str, str]:
    """從 settings.DATABASE_URL 解析 psql 連線參數。"""
    p = urlparse(settings.DATABASE_URL)
    return {
        "host": p.hostname or "localhost",
        "port": str(p.port or 5432),
        "user": p.username or "postgres",
        "password": str(p.password or ""),
        "dbname": p.path.lstrip("/"),
    }


def _safe_db_name(name: str) -> str:
    """庫名會內插進 CREATE/DROP DATABASE 識別字，且 DDL 不可動到非 test 庫。

    用 raise（非 assert，避免 -O 模式被移除）；allowlist 與 sti-implement / sti-cleanup 對齊。
    測試庫名一律以 test 開頭（test_edms / test_edms_gwNN），用 startswith 比子字串更嚴謹。
    """
    if not re.fullmatch(r"[a-z0-9_]+", name) or not name.startswith("test"):
        raise RuntimeError(f"非預期的測試庫名，拒絕用於 DDL: {name!r}")
    return name


def _psql(dbname: str, sql: str) -> subprocess.CompletedProcess:
    """對指定庫執行單句 SQL；失敗即 raise（不靜默吞，避免假根因）。"""
    c = _conn_params()
    env = {**os.environ, "PGPASSWORD": c["password"]}
    result = subprocess.run(  # noqa: S603
        ["psql", "-U", c["user"], "-h", c["host"], "-p", c["port"], "-d", dbname, "-tAc", sql],  # noqa: S607
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql 指令失敗（db={dbname}, sql={sql}）:\n{result.stderr}")
    return result


def _ensure_database(name: str) -> None:
    """建立測試庫（若不存在）。CREATE DATABASE 不可在交易內，連 postgres 維護庫執行。"""
    _safe_db_name(name)
    exists = _psql("postgres", f"SELECT 1 FROM pg_database WHERE datname='{name}'")  # noqa: S608
    if "1" not in exists.stdout:
        _psql("postgres", f'CREATE DATABASE "{name}"')


def _drop_database(name: str) -> None:
    """刪除測試庫（WITH FORCE 終止殘留連線，PG13+）。"""
    _safe_db_name(name)
    _psql("postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _drop_and_recreate_schema(dbname: str) -> None:
    """DROP SCHEMA public CASCADE + CREATE，繞過 FK 衝突徹底清理測試庫。"""
    _safe_db_name(dbname)
    _psql(dbname, "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")


def _is_xdist() -> bool:
    return bool(os.environ.get("PYTEST_XDIST_WORKER"))


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Session 開始前備妥乾淨 schema，結束後清理，保持測試 DB 乾淨。"""
    name = _conn_params()["dbname"]
    # 防呆：確認連的是測試 DB，避免意外操作正式資料。
    # 訊息只顯示 dbname，不印完整 DATABASE_URL（含明文密碼），避免誤設定時憑證外洩進 log。
    assert "test" in settings.DATABASE_URL, f"DATABASE_URL 不含 'test'，疑似連到正式 DB（dbname={name!r}）"
    _safe_db_name(name)

    if _is_xdist():
        # xdist worker：整庫重建（先 DROP 殘留再 CREATE，硬當機可自癒）
        _drop_database(name)
        _ensure_database(name)
    else:
        # 非並行：沿用固定測試庫，缺則建；DROP SCHEMA 清上次殘留
        _ensure_database(name)
        _drop_and_recreate_schema(name)

    # 以子程序執行，避免 asyncio.run() 與 pytest-asyncio session loop 衝突；
    # 繼承 os.environ 的 DATABASE_URL，alembic 據此連到測試庫。
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade head 失敗:\nstdout: {result.stdout}\nstderr: {result.stderr}")

    yield

    if _is_xdist():
        _drop_database(name)
    else:
        _drop_and_recreate_schema(name)


@pytest.fixture(scope="session")
async def test_engine(apply_migrations):
    """Session 級別測試 engine（NullPool，不維持連線池）。"""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(test_engine):
    """每個 test 取得獨立連線，結束後 rollback，不污染資料庫。

    ⚠️ 測試中禁止呼叫 `db.commit()`：本 fixture 靠結束時 rollback 隔離資料，
    一旦 commit 資料會真正落地、無法回滾，造成跨 test 污染。
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()
