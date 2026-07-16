"""密碼策略工具（T016）純單元測試：bcrypt 雜湊 / 強度 / 效期 / 重用（不連 DB）。"""

from datetime import timedelta

import pytest

from app.core.exceptions import AppError
from app.core.password_policy import (
    hash_password,
    is_password_expired,
    is_reused,
    validate_password_strength,
    verify_password,
)
from app.core.utils import utcnow

pytestmark = pytest.mark.unit


def test_hash_verify_roundtrip():
    """雜湊後可驗證；錯誤密碼驗證失敗。"""
    hashed = hash_password("Abcd1234")
    assert hashed != "Abcd1234"  # 非明文
    assert verify_password("Abcd1234", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_enforces_max_length():
    """hash_password 自我強制 72-byte 上限（不依賴呼叫方先 validate）→ DP_PWD_004。"""
    with pytest.raises(AppError) as exc:
        hash_password("x" * 73)
    assert exc.value.error_code == "DP_PWD_004"


def test_hash_uses_random_salt():
    """同一密碼兩次雜湊結果不同（含隨機 salt），但皆可驗證。"""
    h1 = hash_password("Abcd1234")
    h2 = hash_password("Abcd1234")
    assert h1 != h2
    assert verify_password("Abcd1234", h1)
    assert verify_password("Abcd1234", h2)


def test_rejects_too_short():
    """長度不足 → DP_PWD_001。"""
    with pytest.raises(AppError) as exc:
        validate_password_strength("Ab1", min_length=8)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_PWD_001"


def test_accepts_valid_password():
    """達長度且字元種類足 → 通過（不拋）。"""
    validate_password_strength("Abcd1234", min_length=8)  # 小寫+大寫+數字＝3 種


def test_rejects_insufficient_char_types():
    """字元種類不足（僅小寫+數字＝2 種）→ DP_PWD_002。"""
    with pytest.raises(AppError) as exc:
        validate_password_strength("abcd1234", min_length=8, required_char_types=3)
    assert exc.value.error_code == "DP_PWD_002"


def test_accepts_three_char_types():
    """剛好 3 種字元（小寫+數字+特殊）通過。"""
    validate_password_strength("abcd123!", min_length=8, required_char_types=3)


def test_special_char_counts_as_type():
    """特殊字元計為一種類型（小寫+大寫+特殊＝3 種、無數字亦通過）。"""
    validate_password_strength("AbcdEfg!", min_length=8, required_char_types=3)


def test_admin_min_length_enforced():
    """特權門檻 min_length=12：11 碼被拒、12 碼通過。"""
    with pytest.raises(AppError) as exc:
        validate_password_strength("Abcd1234!23", min_length=12)  # 11 碼
    assert exc.value.error_code == "DP_PWD_001"
    validate_password_strength("Abcd1234!234", min_length=12)  # 12 碼


def test_rejects_over_max_length():
    """超過 bcrypt 72-byte 上限 → DP_PWD_004（防靜默截斷造成的強度弱化）。"""
    over = "Aa1!" + "x" * 70  # 74 bytes > 72
    with pytest.raises(AppError) as exc:
        validate_password_strength(over, min_length=8)
    assert exc.value.error_code == "DP_PWD_004"


def test_whitespace_not_counted_as_special():
    """空白不計為特殊字元：小寫+空白+數字＝2 種 → DP_PWD_002。"""
    with pytest.raises(AppError) as exc:
        validate_password_strength("abcdefg 1", min_length=8, required_char_types=3)
    assert exc.value.error_code == "DP_PWD_002"


def test_password_expiry():
    """效期判定：逾期 True、剛好等於效期 True、未逾 False、now 注入、expiry<=0 不過期。"""
    now = utcnow()
    old = now - timedelta(days=91)
    exactly = now - timedelta(days=90)
    recent = now - timedelta(days=30)
    assert is_password_expired(old, 90, now=now) is True
    assert is_password_expired(exactly, 90, now=now) is True  # >= 邊界
    assert is_password_expired(recent, 90, now=now) is False
    assert is_password_expired(old, 0, now=now) is False  # 0＝停用效期
    assert is_password_expired(old, -1, now=now) is False


def test_is_reused():
    """重用檢查：命中最近 hash True、未命中 False、空清單 False。"""
    h1 = hash_password("OldPass1!")
    h2 = hash_password("OldPass2!")
    assert is_reused("OldPass1!", [h1, h2]) is True
    assert is_reused("BrandNew9!", [h1, h2]) is False
    assert is_reused("OldPass1!", []) is False
