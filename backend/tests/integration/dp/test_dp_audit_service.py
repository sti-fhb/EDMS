"""稽核服務 SRVDP003 整合測試（寫入 + 鏈接 + 遮罩，用真實 DB）。"""

import json

import pytest
from sqlalchemy import select

from app.dp.audit.models import DpAuditLog
from app.dp.audit.service import AuditLogService, _compute_row_hash

pytestmark = pytest.mark.integration


async def _fetch_all(db):
    result = await db.execute(select(DpAuditLog).order_by(DpAuditLog.log_id))
    return list(result.scalars().all())


async def test_log_action_writes_row_with_hash(db):
    """log_action 寫入一列，ROW_HASH 非空、標準欄位正確。"""
    svc = AuditLogService()
    await svc.log_action(
        db,
        module="DP",
        func_name="DP-USERS",
        action_type="CREATE",
        result="SUCCESS",
        operator_id="admin01",
        target_id="user001",
        after_value={"user_id": "user001"},
        source_ip="127.0.0.1",
    )

    rows = await _fetch_all(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.created_user == "admin01"
    assert row.result == "SUCCESS"
    assert len(row.row_hash) == 64
    assert row.after_value is not None and "user001" in row.after_value


async def test_second_entry_chains_to_first(db):
    """第二列的 ROW_HASH 確實鏈到第一列（重算驗證）。"""
    svc = AuditLogService()
    await svc.log_action(db, module="DP", func_name="DP-AUTH", action_type="LOGIN", result="SUCCESS", operator_id="u1")
    await svc.log_action(db, module="DP", func_name="DP-AUTH", action_type="LOGOUT", result="SUCCESS", operator_id="u1")

    rows = await _fetch_all(db)
    assert len(rows) == 2
    first, second = rows

    expected = _compute_row_hash(
        prev_hash=first.row_hash,
        module=second.module,
        func_name=second.func_name,
        action_type=second.action_type,
        result=second.result,
        operator_id=second.created_user,
        target_id=second.target_id,
        description=second.description,
        source_ip=second.source_ip,
        before_json=second.before_value,
        after_json=second.after_value,
        created_date=second.created_date,
    )
    assert second.row_hash == expected


async def test_before_after_values_are_masked(db):
    """before/after 內的機密欄位落庫前已遮罩。"""
    svc = AuditLogService()
    await svc.log_action(
        db,
        module="DP",
        func_name="DP-USERS",
        action_type="UPDATE",
        result="SUCCESS",
        operator_id="admin01",
        before_value={"password": "old-secret", "user_name": "小明"},
        after_value={"password": "new-secret", "user_name": "小明"},
    )

    row = (await _fetch_all(db))[0]
    before = json.loads(row.before_value)
    assert before["password"] == "***"
    assert before["user_name"] == "小明"
    assert "old-secret" not in row.before_value
    assert "new-secret" not in row.after_value


async def test_log_action_records_fail_result(db):
    """FAIL 事件（如登入失敗 / 越權拒絕）可寫入。"""
    svc = AuditLogService()
    await svc.log_action(
        db,
        module="DP",
        func_name="DP-AUTH",
        action_type="LOGIN",
        result="FAIL",
        operator_id="attacker",
        description="密碼錯誤",
    )
    row = (await _fetch_all(db))[0]
    assert row.result == "FAIL"
