"""帳號可用性判定（停用 / 鎖定）純單元測試（#250）。

「帳號可用」＝未停用（`STATUS='ACTIVE'`）且未在鎖定中（`LOCKED_UNTIL` 為空或已逾時）。
本判定於 #250 有三個使用點（DP 角色指派檢核、DM 指定審核者下拉、前端列灰化），
故抽為共用函式；鎖定必須比對**當下時間**——過期的鎖定值會留在欄位裡，
誤以 `IS NOT NULL` 判定會讓早已自動解鎖的帳號永遠被當成不可用。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.dp.users.account_status import is_account_usable

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def test_active_never_locked_is_usable():
    """ACTIVE 且從未鎖定（LOCKED_UNTIL 為 null）→ 可用。"""
    assert is_account_usable(status="ACTIVE", locked_until=None, now=_NOW) is True


def test_active_with_expired_lock_is_usable():
    """ACTIVE 且鎖定已逾時 → 可用（逾時自動解鎖，欄位仍留舊值）。"""
    expired = _NOW - timedelta(minutes=1)
    assert is_account_usable(status="ACTIVE", locked_until=expired, now=_NOW) is True


def test_active_with_effective_lock_is_not_usable():
    """ACTIVE 但鎖定未逾時 → 不可用（鎖定中）。"""
    effective = _NOW + timedelta(minutes=30)
    assert is_account_usable(status="ACTIVE", locked_until=effective, now=_NOW) is False


def test_lock_exactly_at_now_is_usable():
    """LOCKED_UNTIL 恰等於當下 → 可用（`<= now` 視為已解鎖，與 dp-users 列表篩選同界線）。"""
    assert is_account_usable(status="ACTIVE", locked_until=_NOW, now=_NOW) is True


def test_disabled_is_not_usable():
    """DISABLED → 不可用（停用需管理者手動啟用，不會自動恢復）。"""
    assert is_account_usable(status="DISABLED", locked_until=None, now=_NOW) is False


def test_disabled_and_locked_is_not_usable():
    """DISABLED 且鎖定中 → 不可用（兩維度獨立，任一不通過即不可用）。"""
    assert is_account_usable(status="DISABLED", locked_until=_NOW + timedelta(hours=1), now=_NOW) is False


def test_unknown_status_fails_closed():
    """非 ACTIVE 的未知狀態值 → 不可用（fail-closed，不因值域擴充而誤放行）。"""
    assert is_account_usable(status="PENDING", locked_until=None, now=_NOW) is False
