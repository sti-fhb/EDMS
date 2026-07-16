"""DP_AUDIT_LOG schema smoke test（T004）。

驗證稽核表 model 可用：Identity 自動產生 LOG_ID、TEXT 欄位（BEFORE/AFTER_VALUE）、
AuditLogBaseModel 標準欄位（僅 CREATED_*）可寫入讀回。
屬 schema plumbing 健康檢查，非 sti-alembic-rules 所禁的 revision 結果驗證。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog

pytestmark = pytest.mark.integration


async def test_audit_log_insert_and_query(db):
    """DP_AUDIT_LOG：不給 LOG_ID 由 Identity 自動產號；TEXT 欄位可寫入讀回。"""
    log = DpAuditLog(
        module="DP",
        func_name="DP-USERS",
        action_type="CREATE",
        target_id="user001",
        result="SUCCESS",
        description="建立使用者",
        source_ip="127.0.0.1",
        before_value=None,
        after_value='{"user_id": "user001"}',
        row_hash="0" * 64,
        created_user="SYSTEM",
        created_date=utcnow(),
    )
    db.add(log)
    await db.flush()

    # Identity 應已自動產生正整數 LOG_ID
    assert log.log_id is not None
    assert log.log_id > 0

    fetched = (await db.execute(select(DpAuditLog).where(DpAuditLog.log_id == log.log_id))).scalar_one()
    assert fetched.action_type == "CREATE"
    assert fetched.after_value == '{"user_id": "user001"}'
