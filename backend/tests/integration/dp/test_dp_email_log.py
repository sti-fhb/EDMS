"""DP_EMAIL_LOG schema smoke test（T007）。

驗證寄件 outbox model 可用：Identity 自動產生 MESSAGE_ID、TEXT body、
新增後可更新狀態欄（STATUS / SENT_DATE，覆蓋 BaseModelNoDelete 的 UPDATED_* 語意）。
屬 schema plumbing 健康檢查。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog

pytestmark = pytest.mark.integration


async def test_email_log_insert_then_update_status(db):
    """插入 PENDING 一列（Identity 產號）→ 更新為 SENT，驗證狀態更新可行。"""
    now = utcnow()
    log = DpEmailLog(
        module="DP",
        template_code="PWD_RESET",
        caller_module="DP",
        recipient="user@edms.example.com",
        subject="【EDMS】密碼重設通知",
        body="請點擊連結重設密碼",
        status="PENDING",
        retry_count=0,
        created_user="SYSTEM",
        created_date=now,
    )
    db.add(log)
    await db.flush()
    assert log.message_id is not None and log.message_id > 0

    # 模擬 worker 寄出後更新狀態（outbox 只更新、不刪除）
    log.status = "SENT"
    log.sent_date = utcnow()
    log.updated_user = "SYSTEM"
    log.updated_date = utcnow()
    await db.flush()

    fetched = (await db.execute(select(DpEmailLog).where(DpEmailLog.message_id == log.message_id))).scalar_one()
    assert fetched.status == "SENT"
    assert fetched.sent_date is not None
