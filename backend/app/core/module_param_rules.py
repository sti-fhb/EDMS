"""模組級參數值域規則註冊表（#528）。

平台級 VALUE 參數（`JWT` / `PWD_POLICY` / `LOGIN` / `MAIL`）的值域寫在
`dp/params/param_rules.py` 的 `_RULES`；模組級（`ET_` / `DM_`）的值域屬**各模組的業務規則**
——例如 `ET_URGENT_REMIND_DAYS` 的 0 是「停用加急提醒」而 `DM_REMIND_THRESHOLD` 的 0 會讓
催辦每日轟炸，兩者下限本來就不同。DP 不得認識模組語彙（`sti-backend-boundaries`），故由
各模組於 bootstrap 把自己的規則註冊進來，DP 經本註冊表查詢。core 為中立處，雙方皆可
import 而不互相耦合內部——與 `module_admin.py` 同一條理由。

`IntRule` 定義於此而非 `dp/params/param_rules.py`：模組若要 import 後者就等於 import DP 內部，
正是上述邊界禁止的事。DP 側改為從本模組 import。

⛔ **刻意不提供 `unregister`。** `module_admin_gate` 有，而它造成過「測試 teardown 清掉
checker，留下正式環境不存在的狀態」的坑（症狀：單獨跑綠、`-n auto` 跑紅），專案裡多處
teardown 因此改為「還原真實 checker」。本註冊表的查無規則方向是 **fail-closed**（見
`validate_param_value`），同一個坑會更痛——清掉規則等於讓該參數在 DP03 變成不可編輯。
要測「未註冊」的行為，用一個從未被註冊的 `PARAM_ID` 即可。
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntRule:
    """整數型參數值域規則；`max_value` 為 None 代表無上限（僅型別 + 下限）。"""

    min_value: int
    max_value: int | None = None

    def __post_init__(self) -> None:
        """擋下寫反的規則。

        `IntRule(30, 1)` 會讓該參數**任何值都被拒**，而使用者看到的只是 422「值不合法」
        ——看起來像自己填錯，不像規則設定錯。在建構時就炸掉，讓它變成啟動期的明顯失敗。
        """
        if self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"值域規則上下限寫反：min={self.min_value} > max={self.max_value}")


class ModuleParamRuleRegistry:
    """聚合各模組提供之參數值域規則，以 (PARAM_ID, PARAM_KEY) 為鍵。"""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], IntRule] = {}

    def register(self, module: str, param_id: str, param_key: str, rule: IntRule) -> None:
        """註冊 / 替換某模組級參數之值域規則（僅限啟動期與測試呼叫，禁置於請求 handler）。

        `module` 不只是標籤：`param_id` 必須以 `{module}_` 起頭，否則拋 `ValueError`。
        這讓「模組 A 為模組 B 的參數註冊規則」「模組搶先為尚未列入平台 `_RULES` 的平台級
        參數註冊一條寬鬆規則」在結構上不可能，而不是靠呼叫順序與查詢順序的慣例。
        違反時於啟動期（`main.py` 模組層）即崩，不會留下半可用狀態。

        Raises:
            ValueError: `param_id` 不屬於該模組。
        """
        prefix = f"{module}_"
        if not param_id.startswith(prefix):
            raise ValueError(f"模組 {module} 不得為 {param_id} 註冊值域規則（須以 {prefix} 起頭）")
        key = (param_id, param_key)
        if key in self._rules:
            # 啟動期非預期的重複註冊（如較寬鬆規則蓋掉正式版）應可被觀測
            logger.warning("模組參數值域規則被覆蓋 param_id=%s param_key=%s", param_id, param_key)
        self._rules[key] = rule

    def get(self, param_id: str, param_key: str) -> IntRule | None:
        """取該參數之值域規則；未註冊回 None（由呼叫端決定 fail 方向）。"""
        return self._rules.get((param_id, param_key))


module_param_rule_registry = ModuleParamRuleRegistry()
