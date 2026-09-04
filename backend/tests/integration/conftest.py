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
        env={**env, "PGCLIENTENCODING": "UTF8"},
        check=False,
        capture_output=True,
        text=True,
        # 同 alembic 子程序之理由：psql 之 NOTICE / 錯誤訊息在 Windows 為 cp950 中文，
        # 以 UTF-8 解碼會在 reader thread 拋 UnicodeDecodeError 並吃掉 stderr，
        # 使上方「psql 指令失敗」的診斷訊息變成空的。
        encoding="utf-8",
        errors="replace",
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
    #
    # ⚠️ 明確指定 UTF-8 兩端：migration 內的 `logger` 訊息為繁體中文（如 ET bootstrap），
    # Windows 上子程序預設以 cp950 輸出、而讀取端以 UTF-8 解碼 → reader thread 拋
    # UnicodeDecodeError。該例外發生在 thread 內不會讓測試失敗，但會**吃掉 stdout**，
    # 使下方 migration 失敗時的診斷訊息變成空的。`errors="replace"` 為最後一道保險：
    # 寧可看到亂碼，也不要失去 alembic 的錯誤輸出。
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8",
        errors="replace",
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

    採 `join_transaction_mode="create_savepoint"`：session 於外層交易內建立 SAVEPOINT，
    被測程式呼叫的 `db.commit()`（如登入失敗須落地的鎖定計數 / FAIL 稽核）只釋放 savepoint、
    不動外層交易，故本 fixture 結束時 `conn.rollback()` 仍能清掉所有測試資料、維持隔離。
    因此測試中呼叫 `commit()` 是安全的（真正落地由外層交易的 rollback 攔下）。
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest.fixture
async def client(db):
    """綁測試 session 的 ASGI client；get_db override 複刻 production 的 commit/rollback 語意。

    override 對成功請求 commit、對例外 rollback，與真實 get_db 一致；因測試 session 採
    savepoint 隔離（見 db fixture），可如實驗證「請求失敗經 rollback 後副作用是否仍落地」。
    lifespan（發信 worker）不隨 ASGITransport 啟動，避免測試期常駐背景任務。
    """
    import httpx
    from httpx import ASGITransport

    import main
    from app.core.db import get_db

    async def _override_get_db():
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    main.app.dependency_overrides[get_db] = _override_get_db
    # raise_app_exceptions=False：未處理例外由 app 的 exception_handler 轉為 500 回應（貼近真實 HTTP），
    # 而非 re-raise 到測試；使「例外 → 500 + 交易回滾」路徑可被驗證。
    transport = ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def backoffice_admin():
    """讓本測試的操作者通過 DP 後台授權閘（#250）。

    DP 後台六個 router 自 #250 起掛 `require_any_module_admin()`（需 ET 或 DM 任一模組
    管理者）。驗「後台功能本身的業務邏輯」而非授權的測試，以本 fixture 註冊 always-true
    的 ET 管理者 checker 即可，不必逐測試建 `ET_USER_ROLE` / `DM_USER_ROLE` 列。

    teardown 還原 `main.py` 註冊之真實 checker——ET 已接線，unregister 會讓後續測試
    看到「未接線」狀態（fail-closed 全 403），比照 test_dp_module_summary.py 之慣例。

    授權行為本身由 `tests/integration/dp/test_dp_backoffice_gate.py` 覆蓋。
    """
    from app.core.module_admin import module_admin_gate
    from app.et.roles.gate import et_is_module_admin

    async def _always_admin(_db, _user_id):
        return True

    module_admin_gate.register("ET", _always_admin)
    yield
    module_admin_gate.register("ET", et_is_module_admin)
