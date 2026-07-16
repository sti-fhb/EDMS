"""DP_PWD_RESET / DP_PWD_HIST schema smoke test（T003）。

驗證兩張新表的 model 可用：對 DP_USER 的 FK、DP_PWD_HIST 複合 PK、
BaseModel / AuditLogBaseModel 標準欄位皆能正確寫入讀回。
屬 schema plumbing 健康檢查，非 sti-alembic-rules 所禁的 revision 結果驗證。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.user.models import DpPwdHistory, DpPwdReset
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db) -> str:
    """建立一個 DP_USER 供 FK 引用，回傳 user_id。"""
    now = utcnow()
    db.add(
        DpUser(
            user_id="pwduser01",
            email="pwduser01@edms.example.com",
            pwd_hash="x" * 20,
            user_name="密碼測試員",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()
    return "pwduser01"


async def test_pwd_reset_insert_and_query(db):
    """DP_PWD_RESET：可寫入並讀回，FK 指向存在的 DP_USER。"""
    user_id = await _make_user(db)
    now = utcnow()
    db.add(
        DpPwdReset(
            token_hash="a" * 64,
            user_id=user_id,
            token_type="PWD_RESET",
            new_email=None,
            expires_date=now,
            used_date=None,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()

    fetched = (await db.execute(select(DpPwdReset).where(DpPwdReset.token_hash == "a" * 64))).scalar_one()
    assert fetched.user_id == user_id
    assert fetched.token_type == "PWD_RESET"


async def test_pwd_history_composite_pk_insert_and_query(db):
    """DP_PWD_HIST：複合 PK（USER_ID + SEQ_NO）可寫入多列並讀回。"""
    user_id = await _make_user(db)
    now = utcnow()
    for seq in (1, 2):
        db.add(
            DpPwdHistory(
                user_id=user_id,
                seq_no=seq,
                pwd_hash=f"hash{seq}",
                created_user="SYSTEM",
                created_date=now,
            )
        )
    await db.flush()

    rows = (
        (await db.execute(select(DpPwdHistory).where(DpPwdHistory.user_id == user_id).order_by(DpPwdHistory.seq_no)))
        .scalars()
        .all()
    )
    assert [r.seq_no for r in rows] == [1, 2]
