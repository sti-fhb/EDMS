"""稽核 ROW_HASH 驗鏈工具整合測試（T052，用真實 DB）。

驗證 verify_chain 走訪 DP_AUTH_LOG 全表（LOG_ID 遞增＝建鏈序）重算並比對存檔 ROW_HASH：
完整鏈回 OK、竄改任一入 hash 之欄位精準指出首斷點、空表回 EMPTY。
竄改以測試專用 raw UPDATE 模擬（正式 repo append-only 無 update 途徑）。
"""

import pytest
from sqlalchemy import text

from app.dp.audit.service import AuditLogService
from app.dp.audit.verify import verify_chain

pytestmark = pytest.mark.integration


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
    await db.execute(
        text('UPDATE "DP_AUDIT_LOG" SET "BEFORE_VALUE" = :v WHERE "LOG_ID" = :id'),
        {"v": '{"status": "TAMPERED"}', "id": victim},
    )

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
    await db.execute(
        text('UPDATE "DP_AUDIT_LOG" SET "ROW_HASH" = :v WHERE "LOG_ID" = :id'),
        {"v": "0" * 64, "id": victim},
    )

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
        await db.execute(
            text('UPDATE "DP_AUDIT_LOG" SET "AFTER_VALUE" = :v WHERE "LOG_ID" = :id'),
            {"v": '{"x": 1}', "id": log_ids[idx]},
        )
    result = await verify_chain(db)
    assert result.status == "BROKEN"
    assert result.first_broken_log_id == log_ids[1]
