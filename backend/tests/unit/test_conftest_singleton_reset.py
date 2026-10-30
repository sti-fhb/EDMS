"""跨測試存活之行程內單例的統一重置（#654）。

integration conftest 的 autouse fixture 以 `tests/_process_singletons.py` 收集並重置所有
限流器 / 冷卻器 / 計數器。本檔驗兩件事，兩者都不需要 DB：

1. **重置確實發生**：把收集到的每個實例弄髒、呼叫重置、斷言全空——而不是只靠「其他測試沒壞」
   當證據（那正是本 issue 要消除的假證據形狀）。
2. **漏納入即變紅**：收集按「型別」反射，同型別的新單例自動涵蓋；剩下的洞是**新的有狀態型別**，
   由型別分類護欄擋住。
"""

import subprocess
import sys
from pathlib import Path

import pytest

import main  # noqa: F401 —— 觸發 router 模組層單例的建立
from app.core.cooldown import VerifySendCooldown
from app.core.rate_limit import SlidingWindowCounter, SlidingWindowRateLimiter
from tests._process_singletons import collect, reset, unclassified_stateful_types

pytestmark = pytest.mark.unit

_SINGLETON_TYPES = (SlidingWindowRateLimiter, SlidingWindowCounter, VerifySendCooldown)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_GUARD_SCRIPT = (
    "import main\n"
    "from tests._process_singletons import unclassified_stateful_types\n"
    "for cls in unclassified_stateful_types(): print(f'UNCLASSIFIED:{cls.__module__}.{cls.__qualname__}')\n"
)
_GUARD_PREFIX = "UNCLASSIFIED:"


def _state(obj) -> dict:
    """單例的內部狀態表（限流器的狀態在其內部 counter）。"""
    if isinstance(obj, SlidingWindowRateLimiter):
        return obj._counter._hits
    if isinstance(obj, SlidingWindowCounter):
        return obj._hits
    return obj._last


def _dirty(obj) -> None:
    if isinstance(obj, SlidingWindowCounter):
        obj.try_record("zz-654")
    else:
        obj.record("zz-654")


def _module_level_singletons() -> dict[str, object]:
    """`app.*` 模組層所有限流器 / 冷卻器 / 計數器（即 issue 盤點的那一類）。"""
    found: dict[str, object] = {}
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith("app."):
            continue
        for attr, value in vars(mod).items():
            if isinstance(value, _SINGLETON_TYPES):
                found[f"{mod_name}.{attr}"] = value
    return found


def test_每個帶可變狀態的_app_型別都已分類():
    """新增一種會累積狀態的型別而沒決定要不要重置 → 紅（AC2）。

    反射以型別為單位：既有型別（限流器 / 冷卻器 / 計數器）的新單例自動被涵蓋，不需要任何人記得。
    反射看不到的只有**新型別**——本護欄要求每個型別都明確歸入「重置」或「不重置」其中一邊。

    ⚠️ 在**全新子行程**裡只 `import main` 後檢查，而不是在本行程：gc 會掃到同一行程內其他測試
    留下的 app 物件（實測：別支測試建的 `UploadAuthPrecheckMiddleware`），使結果隨測試順序漂移。
    子行程看到的正是 integration fixture 收集時的世界。
    """
    result = subprocess.run(  # noqa: S603 —— 固定指令，無外部輸入
        [sys.executable, "-c", _GUARD_SCRIPT],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    # 只取帶前綴的行：import 期間任何模組的 print 不得被誤讀成「未分類型別」
    unclassified = [
        line.removeprefix(_GUARD_PREFIX) for line in result.stdout.splitlines() if line.startswith(_GUARD_PREFIX)
    ]

    assert unclassified == [], (
        "出現未分類、帶可變容器的 app 型別。請判斷它的狀態是否隨請求累積："
        "是 → 加入 tests/_process_singletons.py 的 RESETTERS；"
        "否（如 import 時登記的設定）→ 加入 NOT_RESET 並寫明理由。"
    )


def test_型別護欄認得出未分類的新型別():
    """反證：護欄不是空轉——一個帶 dict 的新 app 型別確實會被抓出來。"""
    fake_type = type("_FakeBucket654", (), {"__module__": "app._fake_654"})
    instance = fake_type()
    instance._hits = {}

    assert fake_type in unclassified_stateful_types()


def test_重置清空所有收集到的單例():
    """把每個實例弄髒後重置 → 全空（AC1 / AC4）。"""
    singletons = collect()
    for obj in singletons:
        _dirty(obj)
    assert all(_state(obj) for obj in singletons), "前提：每個實例都已被弄髒，否則下面的全空不能證明什麼"

    reset(singletons)

    assert [obj for obj in singletons if _state(obj)] == []


def test_收集涵蓋所有模組層單例():
    """issue 列的 DP 15 個、盤點另見的 ET 限流器，皆在收集範圍內（限流器以其內部 counter 計）。"""
    collected = {id(obj) for obj in collect()}
    module_level = _module_level_singletons()
    assert module_level, "前提：import main 後應存在模組層單例"

    def holder(obj) -> object:
        return obj._counter if isinstance(obj, SlidingWindowRateLimiter) else obj

    missing = [name for name, obj in module_level.items() if id(holder(obj)) not in collected]
    assert missing == []


def test_收集涵蓋非模組層持有的實例():
    """藏在 service 屬性裡的冷卻器（`UsersService()` 的預設冷卻）一樣涵蓋——這是選反射而非掃模組屬性的理由。"""
    from app.dp.roles import router as roles_router

    hidden = roles_router._service._users._invite_cooldown

    assert any(obj is hidden for obj in collect())
