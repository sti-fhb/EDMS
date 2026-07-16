"""稽核服務 SRVDP003 純函式單元測試（hash 鏈接 / 遮罩 / 序列化）。"""

import json

import pytest

from app.core.utils import utcnow
from app.dp.audit.service import _compute_row_hash, _mask_sensitive, _to_json

pytestmark = pytest.mark.unit


def _hash(**overrides):
    base = {
        "prev_hash": None,
        "module": "DP",
        "func_name": "DP-USERS",
        "action_type": "CREATE",
        "result": "SUCCESS",
        "operator_id": "admin01",
        "target_id": "user001",
        "description": None,
        "source_ip": "127.0.0.1",
        "before_json": None,
        "after_json": '{"user_id": "user001"}',
        "created_date": utcnow(),
    }
    base.update(overrides)
    return _compute_row_hash(**base)


def test_row_hash_is_deterministic():
    now = utcnow()
    assert _hash(created_date=now) == _hash(created_date=now)


def test_row_hash_is_sha256_hex():
    h = _hash()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_different_prev_hash_yields_different_hash():
    now = utcnow()
    assert _hash(created_date=now, prev_hash=None) != _hash(created_date=now, prev_hash="abc")


def test_tampering_any_field_changes_hash():
    now = utcnow()
    baseline = _hash(created_date=now)
    assert _hash(created_date=now, action_type="DELETE") != baseline
    assert _hash(created_date=now, target_id="other") != baseline
    assert _hash(created_date=now, result="FAIL") != baseline


def test_mask_sensitive_masks_only_sensitive_keys():
    masked = _mask_sensitive({"password": "p@ss", "pwd_hash": "x", "user_name": "小明"})
    assert masked["password"] == "***"
    assert masked["pwd_hash"] == "***"
    assert masked["user_name"] == "小明"


def test_mask_sensitive_recurses_into_nested_structures():
    masked = _mask_sensitive({"outer": {"api_key": "k", "keep": 1}, "list": [{"token": "t"}]})
    assert masked["outer"]["api_key"] == "***"
    assert masked["outer"]["keep"] == 1
    assert masked["list"][0]["token"] == "***"


def test_to_json_none_returns_none():
    assert _to_json(None) is None


def test_to_json_serializes_whitelisted_non_native_types():
    """前後值含 datetime / Decimal / UUID / Enum 等白名單型別時，正確序列化不拋錯。"""
    from datetime import datetime, timezone
    from decimal import Decimal
    from enum import Enum
    from uuid import UUID

    class _Status(Enum):
        ACTIVE = "A"

    result = _to_json(
        {
            "at": datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc),
            "amount": Decimal("12.50"),
            "uid": UUID("12345678-1234-5678-1234-567812345678"),
            "status": _Status.ACTIVE,
        }
    )
    assert result is not None
    parsed = json.loads(result)
    assert parsed["at"].startswith("2026-07-14")
    assert parsed["amount"] == "12.50"
    assert parsed["uid"] == "12345678-1234-5678-1234-567812345678"
    assert parsed["status"] == "A"


def test_to_json_unknown_object_uses_placeholder_not_repr():
    """未知型別（可能 repr 含機密）不以 str(obj) 落庫，改用固定佔位字串避免洩漏。"""

    class _Leaky:
        def __init__(self):
            self.password = "super-secret"

        def __repr__(self):
            return f"_Leaky(password={self.password})"

    # key 'config' 不在機密清單 → 遮罩看不進物件內部；序列化不得吐出 repr
    result = _to_json({"config": _Leaky()})
    assert result is not None
    assert "super-secret" not in result
    assert json.loads(result)["config"] == "<non-serializable>"


def test_mask_sensitive_recurses_into_tuple():
    """tuple 內的機密 key 亦遮罩（tuple 序列化為 JSON 陣列）。"""
    masked = _mask_sensitive({"items": ({"token": "t"},)})
    assert masked["items"][0]["token"] == "***"


def test_to_json_masks_and_sorts_keys():
    result = _to_json({"b": 2, "a": 1, "secret": "s"})
    assert result is not None
    parsed = json.loads(result)
    assert parsed == {"a": 1, "b": 2, "secret": "***"}
    # sort_keys 決定性：a 在 b 之前
    assert result.index('"a"') < result.index('"b"')
