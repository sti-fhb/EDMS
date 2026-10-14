"""密碼長度門檻之共用判定（#623）：管理者套 ADMIN_MIN_LEN、其餘套 MIN_LEN。

變更密碼、忘記密碼重設與兩支「本人適用規則」端點皆經此判定，故判定本身以 unit 釘住；
各呼叫端是否真的走到這裡，由 integration 測試驗（`test_dp_user_password_min_len.py`）。
"""

import pytest

from app.dp.user import password_rules
from app.dp.user.password_rules import PasswordRules, general_rules, rules_for_user

pytestmark = pytest.mark.unit

_PARAMS = {"MIN_LEN": 8, "ADMIN_MIN_LEN": 12, "CHAR_TYPES": 3}


class _FakeParams:
    """只回 PWD_POLICY 三個值的假參數服務；記錄被讀的 key，供斷言「沒有讀錯參數」。"""

    def __init__(self, values=None):
        self.values = values or _PARAMS
        self.read = []

    async def get_int_param(self, db, param_id, key, default):
        assert param_id == "PWD_POLICY"
        self.read.append(key)
        return self.values.get(key, default)


class _FakeGate:
    def __init__(self, admin_modules=()):
        self.admin_modules = set(admin_modules)

    async def is_module_admin(self, module, user_id, db):
        return module in self.admin_modules


@pytest.fixture
def gate(monkeypatch):
    def _install(*admin_modules):
        fake = _FakeGate(admin_modules)
        monkeypatch.setattr(password_rules, "module_admin_gate", fake)
        return fake

    return _install


async def test_一般使用者套用_MIN_LEN(gate):
    gate()
    assert await rules_for_user(None, "u1", params=_FakeParams()) == PasswordRules(min_len=8, char_types=3)


@pytest.mark.parametrize("module", ["ET", "DM"])
async def test_任一模組管理者套用_ADMIN_MIN_LEN(gate, module):
    gate(module)
    assert await rules_for_user(None, "u1", params=_FakeParams()) == PasswordRules(min_len=12, char_types=3)


async def test_管理者門檻跟著參數變(gate):
    gate("ET")
    params = _FakeParams({"MIN_LEN": 8, "ADMIN_MIN_LEN": 14, "CHAR_TYPES": 4})
    assert await rules_for_user(None, "u1", params=params) == PasswordRules(min_len=14, char_types=4)


async def test_一般門檻不查管理者身分(gate):
    """`general_rules` 給未登入、也不知道是誰的情境（註冊 / 啟用）：不得因任何人是管理者而變動。"""
    gate("ET", "DM")
    params = _FakeParams()
    assert await general_rules(None, params=params) == PasswordRules(min_len=8, char_types=3)
    assert "ADMIN_MIN_LEN" not in params.read
