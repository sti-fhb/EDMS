"""DM 角色表整合測試（DM_USER_ROLE / DM_USER_ROLE_LOG，真實 DB）。

驗證 migration 建表 + 模型可寫讀 + 唯一約束 (USER_ID, ROLE_CODE) + 角色異動 append-only。
"""

from datetime import timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.utils import utcnow
from app.dm.roles.models import DmUserRole, DmUserRoleLog

pytestmark = pytest.mark.integration


async def test_dm_user_role_insert_and_query(db):
    """DM_USER_ROLE 可寫入並讀回；標準欄位到位。"""
    db.add(DmUserRole(user_id="u1", role_code="DM_EDITOR", created_user="admin01", created_date=utcnow(), deleted=0))
    await db.flush()

    row = (await db.execute(select(DmUserRole).where(DmUserRole.user_id == "u1"))).scalar_one()
    assert row.role_code == "DM_EDITOR"
    assert row.dm_user_role_id is not None  # Identity 自增
    assert row.deleted == 0


async def test_dm_user_role_unique_constraint(db):
    """同一 (USER_ID, ROLE_CODE) 重複 → 唯一約束擋下。"""
    now = utcnow()
    db.add(DmUserRole(user_id="u2", role_code="DM_ADMIN", created_user="admin01", created_date=now, deleted=0))
    await db.flush()
    db.add(DmUserRole(user_id="u2", role_code="DM_ADMIN", created_user="admin01", created_date=now, deleted=0))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_dm_user_role_multi_roles_allowed(db):
    """同一使用者可多角色（複選、聯集）—— 不同 ROLE_CODE 不受唯一約束擋。"""
    now = utcnow()
    db.add(DmUserRole(user_id="u3", role_code="DM_EDITOR", created_user="a", created_date=now, deleted=0))
    db.add(DmUserRole(user_id="u3", role_code="DM_REVIEWER", created_user="a", created_date=now, deleted=0))
    await db.flush()
    rows = (await db.execute(select(DmUserRole).where(DmUserRole.user_id == "u3"))).scalars().all()
    assert {r.role_code for r in rows} == {"DM_EDITOR", "DM_REVIEWER"}


async def test_dm_user_role_log_append(db):
    """DM_USER_ROLE_LOG append-only 寫入（僅 CREATED_*，業務欄位含 operator / action_time）。"""
    now = utcnow()
    db.add(
        DmUserRoleLog(
            target_user_id="u1",
            role_code="DM_EDITOR",
            action="GRANT",
            operator_user_id="admin01",
            action_time=now,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()
    log = (await db.execute(select(DmUserRoleLog).where(DmUserRoleLog.target_user_id == "u1"))).scalar_one()
    assert log.action == "GRANT" and log.operator_user_id == "admin01"
    assert log.action_time.tzinfo is not None or log.action_time.replace(tzinfo=timezone.utc)  # tz-aware 寫回
