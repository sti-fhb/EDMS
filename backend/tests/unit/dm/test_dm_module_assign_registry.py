"""模組指派轉接層 registry 單元測試（註冊 / 取用 / 未註冊 fail-closed）。"""

import pytest

from app.core.module_assign import module_assign_registry

pytestmark = pytest.mark.unit


class _StubProvider:
    """測試用 stub provider（僅驗 registry 分派，不落地）。"""


def test_register_and_get():
    provider = _StubProvider()
    module_assign_registry.register("ZT", provider)
    assert module_assign_registry.get("ZT") is provider
    module_assign_registry.unregister("ZT")


def test_unregistered_returns_none():
    module_assign_registry.unregister("ZT_ABSENT")
    assert module_assign_registry.get("ZT_ABSENT") is None


def test_register_overwrites():
    p1, p2 = _StubProvider(), _StubProvider()
    module_assign_registry.register("ZT", p1)
    module_assign_registry.register("ZT", p2)
    assert module_assign_registry.get("ZT") is p2
    module_assign_registry.unregister("ZT")
