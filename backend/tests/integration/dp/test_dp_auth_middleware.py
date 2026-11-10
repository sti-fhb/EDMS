"""認證閘 get_jwt_payload（T014）整合測試：每請求查 DP_USER 狀態（真實 DB）。"""

from datetime import timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import create_access_token, get_jwt_payload
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _make_user(db, user_id="user001", *, status="ACTIVE", locked_until=None, deleted=0):
    """建立測試用 DP_USER 並 flush。"""
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=f"{user_id}@edms.local",
        pwd_hash="x",
        user_name="測試員",
        status=status,
        locked_until=locked_until,
        pwd_changed_date=now,
        created_user="admin01",
        created_date=now,
        deleted=deleted,
    )
    db.add(user)
    await db.flush()
    return user


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_valid_token_active_user_passes(db):
    """有效 token + ACTIVE 使用者 → 回 payload。"""
    await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15)
    payload = await get_jwt_payload(credentials=_creds(token), db=db)
    assert payload.sub == "user001"


async def test_missing_credentials_rejected(db):
    """無 Authorization → 401 DP_AUTH_002。"""
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=None, db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"


async def test_invalid_token_rejected(db):
    """竄改 token → 401 DP_AUTH_002（decode 階段即拒，不查 DB）。"""
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token[:-2] + "xx"), db=db)
    assert exc.value.error_code == "DP_AUTH_002"


async def test_deleted_user_rejected(db):
    """token 有效但使用者已軟刪 → 401 DP_AUTH_002（session 失效）。"""
    await _make_user(db, "user001", deleted=1)
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"


async def test_unknown_user_rejected(db):
    """token 有效但 USER_ID 查無 → 401 DP_AUTH_002。"""
    token = create_access_token(sub="ghost", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.error_code == "DP_AUTH_002"


async def test_disabled_user_rejected(db):
    """STATUS=DISABLED → 403 DP_AUTH_004。"""
    await _make_user(db, "user001", status="DISABLED")
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_004"


async def test_locked_user_rejected(db):
    """LOCKED_UNTIL 在未來（鎖定中）→ 403 DP_AUTH_005。"""
    await _make_user(db, "user001", locked_until=utcnow() + timedelta(minutes=30))
    token = create_access_token(sub="user001", ttl_minutes=15)
    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_AUTH_005"


async def test_expired_lock_passes(db):
    """LOCKED_UNTIL 已過（自動解鎖）→ 通過。"""
    await _make_user(db, "user001", locked_until=utcnow() - timedelta(minutes=1))
    token = create_access_token(sub="user001", ttl_minutes=15)
    payload = await get_jwt_payload(credentials=_creds(token), db=db)
    assert payload.sub == "user001"


async def test_token_issued_before_password_change_rejected(db):
    """密碼變更前簽發的 token → 401 DP_AUTH_002（#941）。

    回與其他無效 token 相同的碼：拿著舊 token 的那一方可能正是盜用者，
    不替他指出「密碼剛被改過」。
    """
    user = await _make_user(db, "user001")
    token = create_access_token(sub="user001", ttl_minutes=15, auth_time=utcnow() - timedelta(minutes=10))
    user.pwd_changed_date = utcnow()
    await db.flush()

    with pytest.raises(AppError) as exc:
        await get_jwt_payload(credentials=_creds(token), db=db)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "DP_AUTH_002"


async def test_token_issued_after_password_change_passes(db):
    """變更後重新登入取得的 token → 通過（#941）。

    與上一條配對的正向錨點：少了它，把判定寫成「一律拒絕」也會讓上一條通過，
    而使用者將永遠登不進來。
    """
    user = await _make_user(db, "user001")
    user.pwd_changed_date = utcnow() - timedelta(minutes=10)
    await db.flush()
    token = create_access_token(sub="user001", ttl_minutes=15)

    payload = await get_jwt_payload(credentials=_creds(token), db=db)
    assert payload.sub == "user001"


async def test_password_change_does_not_affect_other_accounts(db):
    """A 改密碼不影響 B 的 token（#941 AC 4）。

    🔴 本條是「這道閘會不會誤殺」的唯一守門：只驗「該失效的失效了」的話，
    把判定式寫成恆 True 也會全綠，而那會讓全系統每個人都登不進來。
    """
    a = await _make_user(db, "userA")
    b = await _make_user(db, "userB")
    # B 的密碼早就改過、之後才登入：auth_time 必然晚於 B 自己的 pwd_changed_date。
    # ⚠️ 不可讓兩者都取當下——同一秒 floor 後相等雖然也會通過，但那是「邊界剛好成立」而非
    # 「B 不受影響」，判準會與另一條邊界測試混在一起。
    b.pwd_changed_date = utcnow() - timedelta(minutes=10)
    await db.flush()
    b_token = create_access_token(sub="userB", ttl_minutes=15)

    a.pwd_changed_date = utcnow()
    await db.flush()

    payload = await get_jwt_payload(credentials=_creds(b_token), db=db)
    assert payload.sub == "userB"
