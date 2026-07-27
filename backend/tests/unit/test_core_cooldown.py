"""VerifySendCooldown 單元測試（#74 重寄驗證信冷卻）。

冷卻器為純記憶體邏輯（不連 DB），故寫 unit。以注入 now（單調時間）決定性驗證，
不依賴真實時間流逝。
"""

import pytest

from app.core.cooldown import VerifySendCooldown
from app.core.exceptions import AppError

pytestmark = pytest.mark.unit

_KEY = "verify-send:acct:a@b.c"
_COOLDOWN = 600.0


def test_check_without_prior_record_passes() -> None:
    """從未 record 過（未曾送信）→ check 不擋（防列舉：不存在的帳號也走到這、不因無紀錄而報錯）。"""
    cd = VerifySendCooldown()
    cd.check(_KEY, _COOLDOWN, now=100.0)  # 不應拋例外


def test_check_within_cooldown_raises_429_with_retry_after() -> None:
    """record 後於冷卻內 check → 429 COMMON_429，retry_after 為剩餘秒（向上取整）。"""
    cd = VerifySendCooldown()
    cd.record(_KEY, now=100.0)
    with pytest.raises(AppError) as exc_info:
        cd.check(_KEY, _COOLDOWN, now=100.0 + 100.0)  # 過了 100 秒，剩 500 秒
    err = exc_info.value
    assert err.status_code == 429
    assert err.error_code == "COMMON_429"
    assert err.retry_after == 500


def test_check_after_cooldown_elapsed_passes() -> None:
    """record 後超過冷卻 → check 放行。"""
    cd = VerifySendCooldown()
    cd.record(_KEY, now=100.0)
    cd.check(_KEY, _COOLDOWN, now=100.0 + 600.0)  # 剛好滿冷卻 → 放行


def test_retry_after_rounds_up_partial_second() -> None:
    """剩餘不足 1 秒也回至少 1（向上取整），避免前端顯示 0 卻仍被擋。"""
    cd = VerifySendCooldown()
    cd.record(_KEY, now=0.0)
    with pytest.raises(AppError) as exc_info:
        cd.check(_KEY, _COOLDOWN, now=599.5)  # 剩 0.5 秒
    assert exc_info.value.retry_after == 1


def test_record_refreshes_window() -> None:
    """再次 record 會刷新冷卻起點（重寄後重新計時）。"""
    cd = VerifySendCooldown()
    cd.record(_KEY, now=100.0)
    cd.record(_KEY, now=400.0)  # 第二次送信刷新
    with pytest.raises(AppError):
        cd.check(_KEY, _COOLDOWN, now=400.0 + 599.0)  # 相對第二次仍在冷卻內
    cd.check(_KEY, _COOLDOWN, now=400.0 + 600.0)  # 相對第二次已滿 → 放行


def test_keys_are_isolated() -> None:
    """不同 key（不同 Email）互不影響。"""
    cd = VerifySendCooldown()
    cd.record("verify-send:acct:a@b.c", now=100.0)
    cd.check("verify-send:acct:x@y.z", _COOLDOWN, now=100.0)  # 另一 key 不受影響
