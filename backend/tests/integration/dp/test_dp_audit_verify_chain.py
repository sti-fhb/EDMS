"""稽核 ROW_HASH 驗鏈工具整合測試（T052，用真實 DB）。

驗證 verify_chain 走訪 DP_AUTH_LOG 全表（LOG_ID 遞增＝建鏈序）重算並比對存檔 ROW_HASH：
完整鏈回 OK、竄改任一入 hash 之欄位精準指出首斷點、空表回 EMPTY。
竄改以測試專用 raw UPDATE 模擬（正式 repo append-only 無 update 途徑）；DB 層 trigger 會擋下
UPDATE（#22），故 `_tamper` 先在測試交易內停用 trigger，交易結束 rollback 即恢復。
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from app.dp.audit import verify
from app.dp.audit.service import AuditLogService
from app.dp.audit.verify import _amain, _cli_session, verify_chain

pytestmark = pytest.mark.integration


def _patch_session_local(monkeypatch, db):
    """把 CLI 入口用的 session 導向測試 session（savepoint 隔離）。"""

    @asynccontextmanager
    async def _fake_session():
        yield db

    monkeypatch.setattr(verify, "_cli_session", _fake_session)


async def _tamper(db, column: str, value: str, log_id: int) -> None:
    """模擬竄改：停用擋改刪的 trigger 後直接 UPDATE（僅存在於本測試交易內，rollback 後恢復）。"""
    assert column in {"BEFORE_VALUE", "AFTER_VALUE", "ROW_HASH"}, column
    await db.execute(text('ALTER TABLE "DP_AUDIT_LOG" DISABLE TRIGGER "TRG_DP_AUDIT_LOG_DENY_MODIFY"'))
    await db.execute(
        text(f'UPDATE "DP_AUDIT_LOG" SET "{column}" = :v WHERE "LOG_ID" = :id'),  # noqa: S608 —— 欄名已白名單
        {"v": value, "id": log_id},
    )


async def _write_rows(db, n: int) -> None:
    """寫入 n 列真稽核（經 log_action，鏈式 ROW_HASH）。"""
    svc = AuditLogService()
    for i in range(n):
        await svc.log_action(
            db,
            module="DP",
            func_name="DP-USERS",
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=f"admin{i:02d}",
            target_id=f"user{i:03d}",
            before_value={"status": "ACTIVE"},
            after_value={"status": "DISABLED"},
            source_ip="127.0.0.1",
        )


async def test_verify_empty_chain_returns_empty(db):
    """空表 → status=EMPTY、total=0、視為完好。"""
    result = await verify_chain(db)
    assert result.status == "EMPTY"
    assert result.total == 0
    assert result.ok is True
    assert result.first_broken_log_id is None


async def test_verify_single_row_ok(db):
    """單列（genesis）鏈完整 → OK。驗 created_date isoformat round-trip 精度。"""
    await _write_rows(db, 1)
    result = await verify_chain(db)
    assert result.status == "OK"
    assert result.total == 1
    assert result.ok is True


async def test_verify_intact_chain_ok(db):
    """多列完整鏈 → OK、total 正確。"""
    await _write_rows(db, 5)
    result = await verify_chain(db)
    assert result.status == "OK"
    assert result.total == 5
    assert result.first_broken_log_id is None


async def test_verify_detects_tampered_before_value(db):
    """竄改某列 BEFORE_VALUE（入 hash 欄位）→ BROKEN，精準指向該列。"""
    await _write_rows(db, 5)
    # 取第 3 列（時間序）的 LOG_ID
    log_ids = list(
        (await db.execute(text('SELECT "LOG_ID" FROM "DP_AUDIT_LOG" ORDER BY "LOG_ID" ASC'))).scalars().all()
    )
    victim = log_ids[2]
    await _tamper(db, "BEFORE_VALUE", '{"status": "TAMPERED"}', victim)

    result = await verify_chain(db)
    assert result.status == "BROKEN"
    assert result.ok is False
    assert result.first_broken_log_id == victim
    assert result.first_broken_func_name == "DP-USERS"
    assert result.first_broken_created_date is not None


async def test_verify_detects_tampered_row_hash(db):
    """直接改某列 ROW_HASH → 該列重算不符 → BROKEN 指向該列。"""
    await _write_rows(db, 4)
    log_ids = list(
        (await db.execute(text('SELECT "LOG_ID" FROM "DP_AUDIT_LOG" ORDER BY "LOG_ID" ASC'))).scalars().all()
    )
    victim = log_ids[1]
    await _tamper(db, "ROW_HASH", "0" * 64, victim)

    result = await verify_chain(db)
    assert result.status == "BROKEN"
    assert result.first_broken_log_id == victim


async def test_verify_reports_first_break_only(db):
    """多列竄改時只回報最早（LOG_ID 最小）的斷點。"""
    await _write_rows(db, 6)
    log_ids = list(
        (await db.execute(text('SELECT "LOG_ID" FROM "DP_AUDIT_LOG" ORDER BY "LOG_ID" ASC'))).scalars().all()
    )
    # 竄改第 2 與第 5 列，應回報第 2 列
    for idx in (1, 4):
        await _tamper(db, "AFTER_VALUE", '{"x": 1}', log_ids[idx])
    result = await verify_chain(db)
    assert result.status == "BROKEN"
    assert result.first_broken_log_id == log_ids[1]


# ── 分批驗鏈（#905 B12）──────────────────────────────────────────────────
# 整表在同一個交易內走訪的話，表很大時長時間持有快照，VACUUM 推進不了；改為每批一個交易。


def _count_commits(monkeypatch, db, on_commit=None) -> list[int]:
    """記錄 verify_chain 結束交易的次數（savepoint fixture 下 commit 只釋放 savepoint，資料仍在）。"""
    calls: list[int] = []
    original = db.commit

    async def _spy() -> None:
        calls.append(1)
        await original()
        if on_commit is not None:
            await on_commit(len(calls))

    monkeypatch.setattr(db, "commit", _spy)
    return calls


async def test_verify_ends_transaction_between_batches(db, monkeypatch):
    """每批各自結束交易：5 列、每批 2 列 → 取上界 1 次 + 3 批（2、2、1）＝ 4 次。"""
    await _write_rows(db, 5)
    commits = _count_commits(monkeypatch, db)

    result = await verify_chain(db, batch_size=2)

    assert result.status == "OK"
    assert result.total == 5
    assert len(commits) == 4


async def test_verify_carries_prev_hash_across_batches(db):
    """批次邊界不能斷鏈：每批第一列要接上前一批最後一列的存檔 hash，完整鏈照樣 OK。"""
    await _write_rows(db, 7)

    result = await verify_chain(db, batch_size=3)

    assert result.status == "OK"
    assert result.total == 7


async def test_verify_detects_break_at_batch_boundary(db):
    """竄改落在下一批第一列時仍抓得到、指向該列（每批重新從 None 接鏈的話會漏掉）。"""
    await _write_rows(db, 6)
    log_ids = list(
        (await db.execute(text('SELECT "LOG_ID" FROM "DP_AUDIT_LOG" ORDER BY "LOG_ID" ASC'))).scalars().all()
    )
    victim = log_ids[3]  # batch_size=3 → 第二批的第一列
    await _tamper(db, "ROW_HASH", "0" * 64, victim)

    result = await verify_chain(db, batch_size=3)

    assert result.status == "BROKEN"
    assert result.first_broken_log_id == victim


async def test_verify_with_expiring_session(db):
    """CLI 的 session 是預設的 `expire_on_commit=True`：commit 後再讀 ORM 欄位會觸發 lazy load 而失敗。

    `db` fixture 是 `expire_on_commit=False`，看不出「先 commit 才讀欄位」的錯；這裡另開一個綁同一條連線、
    會過期的 session，資料仍在同一個測試交易內。
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    await _write_rows(db, 5)
    await db.flush()

    async with AsyncSession(bind=db.bind, join_transaction_mode="create_savepoint") as expiring:
        result = await verify_chain(expiring, batch_size=2)

    assert result.status == "OK"
    assert result.total == 5


async def test_verify_excludes_rows_written_after_start(db, monkeypatch):
    """驗到開始時的最大 LOG_ID 為止：途中新寫入的稽核不算進來，迴圈不會被持續寫入拖著跑。"""
    await _write_rows(db, 4)

    async def _write_during_verify(count: int) -> None:
        if count == 2:  # 第一批結束之後
            await _write_rows(db, 1)

    _count_commits(monkeypatch, db, on_commit=_write_during_verify)

    result = await verify_chain(db, batch_size=2)

    assert result.status == "OK"
    assert result.total == 4


async def test_verify_detects_tail_deleted_during_verify(db, monkeypatch):
    """取上界之後鏈尾被刪（需特權、先停用 trigger）：最後沒讀到上界那一列 → BROKEN，指向上界。

    各批快照不同，刪掉的列之後讀不到；只比對前後兩列的 hash 抓不到「尾巴整段消失」。
    """
    await _write_rows(db, 4)
    upper = (await db.execute(text('SELECT max("LOG_ID") FROM "DP_AUDIT_LOG"'))).scalar()

    async def _delete_tail(count: int) -> None:
        if count == 1:  # 取完上界之後、第一批之前
            await db.execute(text('ALTER TABLE "DP_AUDIT_LOG" DISABLE TRIGGER "TRG_DP_AUDIT_LOG_DENY_MODIFY"'))
            await db.execute(text('DELETE FROM "DP_AUDIT_LOG" WHERE "LOG_ID" = :id'), {"id": upper})

    _count_commits(monkeypatch, db, on_commit=_delete_tail)

    result = await verify_chain(db, batch_size=2)

    assert result.status == "BROKEN"
    assert result.first_broken_log_id == upper
    assert result.total == 3


# ── CLI 入口 `python -m app.dp.audit.verify`（_amain 組裝層 + 退出碼語意）──────────


async def test_amain_ok_returns_exit_0(db, monkeypatch):
    """完整鏈 → CLI 退出碼 0。"""
    await _write_rows(db, 3)
    _patch_session_local(monkeypatch, db)
    assert await _amain() == 0


async def test_amain_broken_returns_exit_1(db, monkeypatch):
    """斷鏈 → CLI 退出碼 1。"""
    await _write_rows(db, 3)
    victim = (await db.execute(text('SELECT "LOG_ID" FROM "DP_AUDIT_LOG" ORDER BY "LOG_ID" ASC'))).scalars().first()
    await _tamper(db, "AFTER_VALUE", '{"tampered": 1}', victim)
    _patch_session_local(monkeypatch, db)
    assert await _amain() == 1


async def test_amain_execution_error_returns_exit_2(db, monkeypatch):
    """執行錯誤（如 DB 連線失敗）→ CLI 退出碼 2，與斷鏈(1)區隔。"""

    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(verify, "_cli_session", _boom)
    assert await _amain() == 2


async def test_cli_的連線不受查詢逾時限制(apply_migrations):
    """#833 C3：稽核表大到單句全表走訪超過 `DB_STATEMENT_TIMEOUT_MS`（60 秒）時，CLI 不可被中止成
    退出碼 2「執行錯誤」——那會讓例行稽核永遠跑不完。比照 migration 設 0。

    正向錨點見 `tests/integration/test_core_db_statement_timeout.py`：應用程式的連線帶 60 秒。
    """
    async with _cli_session() as db:
        setting = (await db.execute(text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"))).scalar()

    assert setting == "0"


async def test_cli_的連線不受閒置交易逾時限制(apply_migrations):
    """#905 A2：全平台設了閒置交易逾時；CLI 比照查詢逾時關掉，與 migration 一致。"""
    async with _cli_session() as db:
        setting = (
            await db.execute(text("SELECT setting FROM pg_settings WHERE name = 'idle_in_transaction_session_timeout'"))
        ).scalar()

    assert setting == "0"


async def test_cli_的連線帶_application_name(apply_migrations):
    """維運要能從 `pg_stat_activity` 認出、必要時中止這條長時間連線。"""
    async with _cli_session() as db:
        name = (await db.execute(text("SELECT current_setting('application_name')"))).scalar()

    assert name == "edms-audit-verify"
