"""模組管理者判定閘（T017）純單元測試：註冊 / fail-closed / stub 注入（不連 DB）。"""

import pytest

from app.core.module_admin import ModuleAdminGate

pytestmark = pytest.mark.unit


async def _always(_db, _user_id):
    return True


async def _never(_db, _user_id):
    return False


async def test_registered_checker_result():
    """已註冊 checker 的結果如實回傳。"""
    gate = ModuleAdminGate()
    gate.register("ET", _always)
    gate.register("DM", _never)
    assert await gate.is_module_admin("ET", "u1", db=None) is True
    assert await gate.is_module_admin("DM", "u1", db=None) is False


async def test_unregistered_module_denies():
    """未註冊模組 → False（fail-closed，未接線＝非管理者）。"""
    gate = ModuleAdminGate()
    assert await gate.is_module_admin("ET", "u1", db=None) is False


async def test_stub_injection_and_unregister():
    """stub 可注入替換、可 unregister 還原為 fail-closed。"""
    gate = ModuleAdminGate()
    gate.register("ET", _never)
    assert await gate.is_module_admin("ET", "u1", db=None) is False
    # 以另一 stub 替換
    gate.register("ET", _always)
    assert await gate.is_module_admin("ET", "u1", db=None) is True
    # 移除後回 fail-closed
    gate.unregister("ET")
    assert await gate.is_module_admin("ET", "u1", db=None) is False


def test_unregister_unknown_is_noop():
    """unregister 未註冊模組不拋錯。"""
    gate = ModuleAdminGate()
    gate.unregister("NOPE")  # 不應拋例外


async def test_truthy_non_bool_fails_closed():
    """checker 回傳 truthy 非 bool（如角色清單）→ 嚴格收斂為 False，不 fail-open。"""

    async def _returns_list(_db, _user_id):
        return ["ADMIN"]  # truthy 但非 True

    gate = ModuleAdminGate()
    gate.register("ET", _returns_list)
    assert await gate.is_module_admin("ET", "u1", db=None) is False


async def test_any_module_admin_true_when_only_one_matches():
    """任一模組為管理者即 True（#250：DP 後台門檻為「ET 或 DM 任一管理者」）。"""
    gate = ModuleAdminGate()
    gate.register("ET", _never)
    gate.register("DM", _always)
    assert await gate.is_any_module_admin(("ET", "DM"), "u1", db=None) is True
    # 順序無關：先命中者提前回傳，兩種排列結果相同
    assert await gate.is_any_module_admin(("DM", "ET"), "u1", db=None) is True


async def test_any_module_admin_false_when_none_matches():
    """全部模組皆非管理者 → False（該使用者看不到 / 進不了 DP 後台）。"""
    gate = ModuleAdminGate()
    gate.register("ET", _never)
    gate.register("DM", _never)
    assert await gate.is_any_module_admin(("ET", "DM"), "u1", db=None) is False


async def test_any_module_admin_unregistered_fails_closed():
    """模組皆未註冊 → False（fail-closed，未接線＝非管理者）。"""
    gate = ModuleAdminGate()
    assert await gate.is_any_module_admin(("ET", "DM"), "u1", db=None) is False


async def test_any_module_admin_empty_modules_is_false():
    """未指定任何模組 → False（不得因空集合而放行）。"""
    gate = ModuleAdminGate()
    gate.register("ET", _always)
    assert await gate.is_any_module_admin((), "u1", db=None) is False


async def test_any_module_admin_survives_checker_exception():
    """某模組 checker 炸掉不影響其他模組判定（該模組視為 False，不整體 500）。"""

    async def _boom(_db, _user_id):
        raise RuntimeError("boom")

    gate = ModuleAdminGate()
    gate.register("ET", _boom)
    gate.register("DM", _always)
    assert await gate.is_any_module_admin(("ET", "DM"), "u1", db=None) is True


async def test_checker_exception_fails_closed():
    """checker 執行期拋例外 → fail-closed 回 False，不向上傳播。"""

    async def _boom(_db, _user_id):
        raise RuntimeError("checker 內部炸了")

    gate = ModuleAdminGate()
    gate.register("ET", _boom)
    assert await gate.is_module_admin("ET", "u1", db=None) is False
