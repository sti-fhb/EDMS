"""JWT 基礎（T013）純單元測試：簽發 / 解碼 / TTL / 換發上限（不連 DB）。"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.auth import (
    create_access_token,
    decode_access_token,
    renew_access_token,
    token_issued_before_password_change,
)
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow

pytestmark = pytest.mark.unit


def test_create_and_decode_roundtrip():
    """簽發後可解碼，sub 與 auth_time 正確帶回。"""
    at = utcnow() - timedelta(minutes=3)
    token = create_access_token(sub="user001", ttl_minutes=15, auth_time=at)
    payload = decode_access_token(token)
    assert payload.sub == "user001"
    # auth_time 以秒精度存 epoch，比對秒數
    assert int(payload.auth_time.timestamp()) == int(at.timestamp())


def test_access_token_ttl_applied():
    """exp − iat 等於 ttl_minutes。"""
    token = create_access_token(sub="u1", ttl_minutes=15)
    payload = decode_access_token(token)
    assert int((payload.exp - payload.iat).total_seconds()) == 15 * 60


def test_fresh_token_auth_time_defaults_to_now():
    """未指定 auth_time（新登入）時預設為簽發當下。"""
    before = utcnow()
    payload = decode_access_token(create_access_token(sub="u1", ttl_minutes=15))
    assert abs((payload.auth_time - before).total_seconds()) < 5


def test_decode_rejects_tampered_token():
    """竄改 token 內容 → DP_AUTH_002。"""
    token = create_access_token(sub="u1", ttl_minutes=15)
    tampered = token[:-3] + ("abc" if token[-3:] != "abc" else "xyz")
    with pytest.raises(AppError) as exc:
        decode_access_token(tampered)
    assert exc.value.error_code == "DP_AUTH_002"
    assert exc.value.status_code == 401


def test_decode_rejects_expired_token():
    """已過期 token → DP_AUTH_002。"""
    token = create_access_token(sub="u1", ttl_minutes=-1)  # exp 在過去
    with pytest.raises(AppError) as exc:
        decode_access_token(token)
    assert exc.value.error_code == "DP_AUTH_002"


def test_decode_rejects_alg_none():
    """alg=none 的偽造 token（演算法混淆）→ 被拒。"""
    forged = jwt.encode({"sub": "attacker"}, key="", algorithm="none")
    with pytest.raises(AppError) as exc:
        decode_access_token(forged)
    assert exc.value.error_code == "DP_AUTH_002"


def test_decode_rejects_wrong_secret():
    """以他人密鑰簽的 token → 被拒。"""
    now = utcnow()
    forged = jwt.encode(
        {
            "sub": "u1",
            "auth_time": int(now.timestamp()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
        },
        key=settings.JWT_SECRET_KEY + "_wrong",
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(AppError) as exc:
        decode_access_token(forged)
    assert exc.value.error_code == "DP_AUTH_002"


def test_renew_preserves_auth_time():
    """換發沿用原 auth_time，並簽發新的 exp。"""
    at = utcnow() - timedelta(hours=2)
    token = create_access_token(sub="u1", ttl_minutes=15, auth_time=at)
    original = decode_access_token(token)
    renewed = decode_access_token(renew_access_token(token, ttl_minutes=15, renew_max_hours=8))
    assert int(renewed.auth_time.timestamp()) == int(at.timestamp())
    assert renewed.exp >= original.exp


def test_renew_rejects_beyond_window():
    """auth_time 距今已超過換發上限 → DP_AUTH_003。"""
    at = utcnow() - timedelta(hours=9)
    token = create_access_token(sub="u1", ttl_minutes=15, auth_time=at)
    with pytest.raises(AppError) as exc:
        renew_access_token(token, ttl_minutes=15, renew_max_hours=8)
    assert exc.value.error_code == "DP_AUTH_003"
    assert exc.value.status_code == 401


def test_renew_rejects_at_exact_window_boundary():
    """剛好達換發上限（>= 語意）即拒絕，鎖定邊界不被誤改為 >。"""
    # 略微超過整數上限以避開執行期間經過的毫秒，穩定觸發 >= 邊界
    at = utcnow() - timedelta(hours=8, seconds=1)
    token = create_access_token(sub="u1", ttl_minutes=15, auth_time=at)
    with pytest.raises(AppError) as exc:
        renew_access_token(token, ttl_minutes=15, renew_max_hours=8)
    assert exc.value.error_code == "DP_AUTH_003"


def test_decode_rejects_token_missing_claim():
    """以正確密鑰簽出但缺必要 claim（auth_time）→ DP_AUTH_002（走 KeyError 分支）。"""
    now = utcnow()
    forged = jwt.encode(
        {"sub": "u1", "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=15)).timestamp())},
        key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(AppError) as exc:
        decode_access_token(forged)
    assert exc.value.error_code == "DP_AUTH_002"


def test_renew_rejects_invalid_token():
    """換發時現行 token 無效（過期/竄改）→ DP_AUTH_002，不得換發。"""
    expired = create_access_token(sub="u1", ttl_minutes=-1, auth_time=utcnow())
    with pytest.raises(AppError) as exc:
        renew_access_token(expired, ttl_minutes=15, renew_max_hours=8)
    assert exc.value.error_code == "DP_AUTH_002"


class TestTokenIssuedBeforePasswordChange:
    """密碼變更後使變更前簽發之 token 失效的判定（#941）。

    `auth_time` 由 epoch **整數秒**還原（`_epoch_to_dt`），微秒恆為 0；
    `PWD_CHANGED_DATE` 為 `TIMESTAMPTZ`、帶微秒。兩者直接比會把「同一秒內改完密碼又登入」
    的新 token 誤判成舊的，故比較前須把 `pwd_changed_date` 取整秒。
    """

    def test_早於變更時間者為舊_token(self):
        changed = datetime(2026, 11, 10, 8, 0, 1, 500000, tzinfo=timezone.utc)
        auth_time = datetime(2026, 11, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert token_issued_before_password_change(auth_time, changed) is True

    def test_晚於變更時間者不是舊_token(self):
        changed = datetime(2026, 11, 10, 8, 0, 1, 500000, tzinfo=timezone.utc)
        auth_time = datetime(2026, 11, 10, 8, 0, 2, tzinfo=timezone.utc)
        assert token_issued_before_password_change(auth_time, changed) is False

    # 🥇 本組唯一抓得到「忘了取整秒」的案例。直接比 datetime 時
    # 08:00:01.000000 < 08:00:01.500000 成立 → 剛登入的新 token 會被誤拒而無限登出迴圈；
    # 取整秒後兩者相等、不成立。上面兩條在有沒有取整秒時答案都一樣，證明不了這件事。
    def test_同一秒內改完密碼又登入者不得被誤拒(self):
        changed = datetime(2026, 11, 10, 8, 0, 1, 500000, tzinfo=timezone.utc)
        auth_time = datetime(2026, 11, 10, 8, 0, 1, tzinfo=timezone.utc)
        assert token_issued_before_password_change(auth_time, changed) is False

    def test_變更時間本身無微秒時邊界仍正確(self):
        changed = datetime(2026, 11, 10, 8, 0, 1, tzinfo=timezone.utc)
        assert token_issued_before_password_change(changed - timedelta(seconds=1), changed) is True
        assert token_issued_before_password_change(changed, changed) is False
        assert token_issued_before_password_change(changed + timedelta(seconds=1), changed) is False
