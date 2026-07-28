"""#34 登入失敗計數原子化整合測試。

驗 `AuthRepository.increment_login_fail` 為 DB 端原子遞增（基於 DB 現值、非 stale ORM），
達門檻同一 UPDATE 設 locked_until，並回傳遞增後新計數。避免 ORM 讀改寫的 lost update。
"""

from datetime import timedelta

import pytest

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_THRESHOLD = 5


async def _make_user(db, *, user_id="u_fail", fail_count=0):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name="測試員",
            status="ACTIVE",
            login_fail_count=fail_count,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _incr(db, user_id, now):
    return await AuthRepository().increment_login_fail(
        db,
        user_id=user_id,
        threshold=_THRESHOLD,
        lock_until=now + timedelta(minutes=30),
        operator_id="SYSTEM",
        now=now,
    )


async def test_increment_returns_new_count_from_db_value(db):
    """連續遞增基於 DB 現值累加、回傳遞增後計數（非 stale ORM +=，故不會 lost update）。"""
    await _make_user(db, user_id="u1", fail_count=0)
    now = utcnow()
    assert await _incr(db, "u1", now) == 1
    assert await _incr(db, "u1", now) == 2
    assert await _incr(db, "u1", now) == 3
    user = await AuthRepository().get_by_user_id(db, "u1")
    assert user.login_fail_count == 3
    assert user.locked_until is None  # 未達門檻不鎖


async def test_increment_locks_when_threshold_reached(db):
    """遞增後達門檻 → 同一 UPDATE 設 locked_until，回傳計數 == 門檻。"""
    await _make_user(db, user_id="u2", fail_count=_THRESHOLD - 1)  # 4
    now = utcnow()
    new_count = await _incr(db, "u2", now)
    assert new_count == _THRESHOLD  # 5
    user = await AuthRepository().get_by_user_id(db, "u2")
    assert user.login_fail_count == _THRESHOLD
    assert user.locked_until is not None  # 達門檻鎖定


async def test_increment_returns_none_when_row_absent(db):
    """帳號不存在 / 已軟刪（WHERE deleted=0 比對 0 列）→ 回 None，供 service 走帳號不存在路徑。"""
    await _make_user(db, user_id="u3", fail_count=1)
    await db.execute(DpUser.__table__.update().where(DpUser.user_id == "u3").values(DELETED=1))
    now = utcnow()
    assert await _incr(db, "u3", now) is None  # 已軟刪，不遞增
