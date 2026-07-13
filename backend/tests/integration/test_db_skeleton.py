"""測試 DB 骨架 smoke test：驗證 integration fixture plumbing 可用。

證明 apply_migrations 讓 DP_USER 表落地、db fixture 連得上、rollback 生效。
這是測試基礎建設本身的健康檢查，非 sti-alembic-rules 所禁的
「特定 revision 結果驗證」（不斷言欄位型別 / NOT NULL 等 schema 細節）。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def test_db_fixture_insert_and_query(db):
    """db fixture 可寫入並讀回 DP_USER；session 結束自動 rollback，不留資料。"""
    db.add(
        DpUser(
            user_id="tester01",
            email="tester01@edms.example.com",
            pwd_hash="x" * 20,
            user_name="測試員01",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=utcnow(),
            must_change_pwd=False,
            created_user="SYSTEM",
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()

    fetched = (await db.execute(select(DpUser).where(DpUser.user_id == "tester01"))).scalar_one()
    assert fetched.email == "tester01@edms.example.com"
    assert fetched.status == "ACTIVE"
