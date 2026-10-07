"""ET 模組級參數的值域規則（#528）。

值域屬 ET 的業務規則而非 DP 的，故定義於此、由 `bootstrap.register_et_module()` 註冊進
`core/module_param_rules` 的註冊表供 DP 查詢（DP 不得認識模組語彙，見
`sti-backend-boundaries`）。

本檔刻意只依賴 `app.core`：`bootstrap` 於啟動期 import 它，拉進 service 層會增加循環
import 的風險。
"""

from app.core.module_param_rules import IntRule

URGENT_REMIND_DAYS_PARAM_ID = "ET_URGENT_REMIND_DAYS"

# 值域 0–30。ET spec（`docs/specs/et/data-model.md`）只寫「純業務門檻，由 ET 管理者自行
# 調整」未載值域，故為 #528 裁示值。
#
# ⚠️ **下限是 0 不是 1**，與 DM_REMIND_THRESHOLD 不同。`schedules/rules.py` 的
# `needs_urgent_remind` docstring 明寫「`urgent_days = 0` 因「已到期」閘而等於停用加急提醒
# ——這是合理的停用語意」。擋掉 0 會移除一個有文件記載的功能。
# （#528 的 AC1 原文是「至少擋負數與零」，本條刻意偏離，裁示記於該 issue 留言。）
#
# 負數仍擋：它同樣造成靜默停用（窗口寬度為負，永不觸發），但沒有任何文件說它該這樣，
# 是重複且令人困惑的第二條停用路徑。
# 上限 30：窗口大於課程長度時所有課程一開課就收到「即將截止」；且超過一個月不叫「加急」。
URGENT_REMIND_DAYS_RULE = IntRule(0, 30)
