"""跨測試存活的行程內單例：收集與重置（#654）。

限流器 / 冷卻器 / 計數器是 module-level 單例，狀態放在行程內記憶體——`db` fixture 的
savepoint + rollback 只隔離**資料**，管不到它們。漏清的症狀不是變紅：例如 `_overwrite_counter`
額度用罄後 `/register` 走靜默路徑回 202，斷言「沒寄第二封信」的測試會**為錯的理由通過**。

## 為何用反射（gc 掃描）而非顯式清單

- 新增同型別的單例**自動涵蓋**，不需要任何人知道這裡存在
- 涵蓋**不在模組層**的實例：`UsersService()` 的預設冷卻器掛在 `RolesService._users`、
  `AccountQueryService._users` 底下，掃模組屬性看不到
- 反射看不到的只剩「新的有狀態**型別**」——由 `unclassified_stateful_types()` 的護欄測試擋住
  （`tests/unit/test_conftest_singleton_reset.py`），漏分類即變紅

## 前提

只收 `import main` 時就存在的實例（integration conftest 於 `app_imported` 之後收集一次；每條測試
都掃 gc 約 50ms，乘上近千條測試不划算）。測試內自行建立的實例屬該測試自己，不在此列。

⚠️ 型別護欄的盲區（皆為已知取捨，目前盤點無實際漏網）：

- **延遲建立**的實例：首次請求才建立的 middleware、lifespan 內建立的物件。現有例子
  `UploadAuthPrecheckMiddleware._in_flight` 於請求結束即遞減歸零，不跨請求累積
- 只持有**標量**狀態（`int` / `float`）的型別、`__slots__` 型別
- 模組層的**裸容器**（如 `_inflight: set = set()`），它不是 app 類別的實例

日後若以上述形狀實作限流 / 計數，須自行加入 `RESETTERS`（或改為既有型別），護欄不會提醒。
"""

import gc
from collections import deque
from collections.abc import Callable, Iterable

from app.core.cooldown import VerifySendCooldown
from app.core.module_admin import ModuleAdminGate
from app.core.module_assign import ModuleAssignRegistry
from app.core.module_param_rules import ModuleParamRuleRegistry
from app.core.module_provisioning import ModuleProvisioningGate
from app.core.module_roles import ModuleRoleGate
from app.core.rate_limit import SlidingWindowCounter
from app.core.upload_form_limits import LimitedFormRoute
from app.dp.notify.service import _SafeFormatter

# 狀態隨請求累積的型別 → 清法。
# `SlidingWindowRateLimiter` 不在表內：它的狀態全在內部的 `_counter`（SlidingWindowCounter），
# gc 會把那個 counter 當獨立物件收進來，同一份狀態只留一個清法。
RESETTERS: dict[type, Callable[[object], None]] = {
    SlidingWindowCounter: lambda obj: obj._hits.clear(),
    VerifySendCooldown: lambda obj: obj._last.clear(),
}

# 帶可變容器、但**不得**重置的型別 → 理由。它們的內容是 import 時的登記 / 設定，清掉等於拔掉接線。
NOT_RESET: dict[type, str] = {
    ModuleAdminGate: "main 於 import 時註冊模組 checker；清掉即全面 fail-closed",
    ModuleRoleGate: "同上，模組角色 checker 的登記表",
    ModuleAssignRegistry: "同上，模組指派 provider 的登記表",
    ModuleParamRuleRegistry: "同上，模組參數規則的登記表",
    ModuleProvisioningGate: "同上，模組開通 granter 的登記表",
    LimitedFormRoute: "FastAPI 路由定義（dependencies / responses 等），非請求狀態",
    _SafeFormatter: "建構時固定的字元轉換表，不隨請求變動",
}

_MUTABLE = (dict, list, set, deque)


def collect() -> list[object]:
    """回傳目前行程內所有需重置的單例（型別在 `RESETTERS` 內）。"""
    return [obj for obj in gc.get_objects() if type(obj) in RESETTERS]


def reset(singletons: Iterable[object]) -> None:
    """把每個單例的狀態清空。"""
    for obj in singletons:
        RESETTERS[type(obj)](obj)


def unclassified_stateful_types() -> set[type]:
    """`app.*` 類別的實例中，屬性含可變容器、卻不在 `RESETTERS` / `NOT_RESET` 任一表的型別。

    先以型別所屬模組過濾、再碰 `__dict__`：第三方物件（如 pydantic 的 mock）取屬性可能拋例外。
    """
    classified = RESETTERS.keys() | NOT_RESET.keys()
    found: set[type] = set()
    for obj in gc.get_objects():
        cls = type(obj)
        if cls in classified or cls in found or isinstance(obj, type) or not cls.__module__.startswith("app."):
            continue
        try:
            attrs = vars(obj)
        except TypeError:  # __slots__ 類別無 __dict__
            continue
        if any(isinstance(value, _MUTABLE) for value in attrs.values()):
            found.add(cls)
    return found
