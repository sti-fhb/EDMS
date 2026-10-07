"""DM 模組級參數的值域規則（#528）。

值域屬 DM 的業務規則而非 DP 的，故定義於此、由 `bootstrap.register_dm_module()` 註冊進
`core/module_param_rules` 的註冊表供 DP 查詢（DP 不得認識模組語彙，見
`sti-backend-boundaries`）。

> `docs/specs/dm/issues.md` 曾把「參數值域校驗落點於 DP 定義端或 DM 端」列為開工前待與 SA
> 確認的未決項，本檔即該題的答案：**DM 端定義、經平台註冊表交付**。

本檔刻意只依賴 `app.core`：`bootstrap` 於啟動期 import 它，拉進 service 層會增加循環
import 的風險。
"""

from app.core.module_param_rules import IntRule

REMIND_THRESHOLD_PARAM_ID = "DM_REMIND_THRESHOLD"

# 值域 1–30，**DM spec 明載**（`docs/specs/dm/research.md`：「預設 7、可調 1–30」；
# `docs/specs/dm/issues.md` 同），非本次發明。
#
# ⚠️ **下限是 1 不是 0**，與 ET_URGENT_REMIND_DAYS 不同。`review/repository.py` 以
# `cutoff = utcnow() - timedelta(days=threshold_days)` 取門檻、條件為 `submit_date <= cutoff`：
#   0  → cutoff 就是 now        → 所有 PENDING 都符合
#   -1 → cutoff 落在「明天」    → 同樣全中
# 而 DM 側沒有 ET 那種 `URGENT_REMIND_SENT` 防重複旗標，`SCHDM002` 每日執行，所以會變成
# 每個待簽核項目的審核者**每天都收到催辦信且不會停**。
# 上限 30：設大使 cutoff 落在很久以前，幾乎沒有項目符合 → 催辦靜默停擺。
REMIND_THRESHOLD_RULE = IntRule(1, 30)
