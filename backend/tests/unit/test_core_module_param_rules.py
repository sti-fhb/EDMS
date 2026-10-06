"""模組級參數值域規則註冊表單元測試（#528）。"""

import pytest

from app.core.module_param_rules import IntRule, ModuleParamRuleRegistry, module_param_rule_registry

pytestmark = pytest.mark.unit


def test_註冊後取得同一條規則():
    reg = ModuleParamRuleRegistry()
    reg.register("ZZ", "ZZ_THING", "VALUE", IntRule(1, 30))
    assert reg.get("ZZ_THING", "VALUE") == IntRule(1, 30)


def test_未註冊回_none():
    reg = ModuleParamRuleRegistry()
    assert reg.get("ZZ_THING", "VALUE") is None


def test_param_key_是鍵的一部分():
    """同一 PARAM_ID 下不同 key 各自獨立——平台級 _RULES 同樣以 (id, key) 為鍵。"""
    reg = ModuleParamRuleRegistry()
    reg.register("ZZ", "ZZ_GROUP", "A", IntRule(1, 10))
    assert reg.get("ZZ_GROUP", "A") == IntRule(1, 10)
    assert reg.get("ZZ_GROUP", "B") is None


def test_重複註冊以後者為準():
    """冪等：bootstrap 於測試中可能重入，重複註冊不得拋錯。"""
    reg = ModuleParamRuleRegistry()
    reg.register("ZZ", "ZZ_THING", "VALUE", IntRule(1, 30))
    reg.register("ZZ", "ZZ_THING", "VALUE", IntRule(0, 5))
    assert reg.get("ZZ_THING", "VALUE") == IntRule(0, 5)


def test_沒有_unregister_方法():
    """刻意不提供 unregister（#528 設計決定）。

    `module_admin_gate` 有 unregister，而它造成過「測試 teardown 清掉 checker，留下正式
    環境不存在的狀態」的坑（症狀：單獨跑綠、`-n auto` 跑紅），專案裡多處 teardown 因此
    改為「還原真實 checker」而非 unregister。

    本註冊表的 fail-closed 方向使同一個坑更痛——清掉規則會讓該參數在 DP03 變成不可編輯。
    要測「未註冊」的行為，用一個**從未被註冊的 PARAM_ID**即可，不需要先拆掉真的那條。
    """
    assert not hasattr(ModuleParamRuleRegistry, "unregister")


def test_全域單例可用且與新實例隔離():
    """`module_param_rule_registry` 為 DP 查詢的單一入口；新建實例不得共用狀態。"""
    assert module_param_rule_registry.get("ZZ_NEVER_REGISTERED", "VALUE") is None
    reg = ModuleParamRuleRegistry()
    reg.register("ZZ", "ZZ_LOCAL_ONLY", "VALUE", IntRule(1))
    assert module_param_rule_registry.get("ZZ_LOCAL_ONLY", "VALUE") is None


# ---- 把慣例變成不變量（#528 Security Review L-1 / L-2）----


@pytest.mark.parametrize(
    ("module", "param_id"),
    [
        ("DM", "ET_URGENT_REMIND_DAYS"),  # 模組 A 搶註冊模組 B 的參數
        ("DM", "LOGIN"),  # 模組搶註冊平台級參數
        ("DM", "DMX_SOMETHING"),  # 前綴相似但不相符
    ],
)
def test_模組不得為不屬於自己的參數註冊規則(module, param_id):
    """否則「誰的規則生效」會取決於 main.py 的呼叫順序，而唯一的跡象只有一行 warning。

    查詢順序（平台 `_RULES` 優先）已使模組蓋不掉**既有**平台規則，但擋不住模組搶先為
    「尚未列入 _RULES 的平台級參數」註冊一條寬鬆規則。前綴檢核讓這件事結構上不可能。
    """
    reg = ModuleParamRuleRegistry()
    with pytest.raises(ValueError, match="不得為"):
        reg.register(module, param_id, "VALUE", IntRule(1, 30))


def test_上下限寫反時於建構即拋():
    """`IntRule(30, 1)` 會讓該參數任何值都被拒，而症狀是 422「值不合法」——看起來像
    使用者填錯、不像規則設錯。在建構時炸掉，讓它變成啟動期的明顯失敗。
    """
    with pytest.raises(ValueError, match="上下限寫反"):
        IntRule(30, 1)


def test_無上限與上下限相等皆合法():
    assert IntRule(1).max_value is None
    assert IntRule(5, 5).min_value == 5
