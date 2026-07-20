"""強制變更密碼閘（T023）整合測試：MUST_CHANGE_PWD 旗標 / 密碼逾效期 → 403 DP_AUTH_009。"""

from datetime import timedelta

import pytest

from app.core.auth import JwtPayload
from app.core.exceptions import AppError
from app.core.password_gate import require_password_current
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, *, user_id, must_change=False, pwd_changed_days_ago=1):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=f"{user_id}@edms.local",
        pwd_hash=hash_password("Abcd1234"),
        user_name="閘測試",
        status="ACTIVE",
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=pwd_changed_days_ago),
        must_change_pwd=must_change,
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


def _payload(sub):
    now = utcnow()
    return JwtPayload(sub=sub, auth_time=now, iat=now, exp=now + timedelta(minutes=15))


async def test_gate_allows_current_password(db):
    """密碼現行有效（旗標 False + 未逾效期）→ 放行、回原 payload。"""
    await _make_user(db, user_id="cur", pwd_changed_days_ago=1)
    result = await require_password_current(payload=_payload("cur"), db=db)
    assert result.sub == "cur"


async def test_gate_blocks_must_change_flag(db):
    """MUST_CHANGE_PWD=true → 403 DP_AUTH_009。"""
    await _make_user(db, user_id="mc", must_change=True)
    with pytest.raises(AppError) as exc:
        await require_password_current(payload=_payload("mc"), db=db)
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_AUTH_009"


async def test_gate_blocks_expired_password(db):
    """密碼逾效期（種子 EXPIRY_DAYS=90）→ 403 DP_AUTH_009。"""
    await _make_user(db, user_id="exp", pwd_changed_days_ago=91)
    with pytest.raises(AppError) as exc:
        await require_password_current(payload=_payload("exp"), db=db)
    assert exc.value.error_code == "DP_AUTH_009"
