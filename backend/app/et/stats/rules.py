"""週統計之純業務規則（US14 / #325）。

**完全不碰 DB**：快照的六個數字全由「每位學員的 `(完成項目數, 總項目數)`」導出。

## 不讀 `ET_ENROLLMENT.COMPLETION_STATUS`

那欄只在加入課程時寫入 `NOT_STARTED`，**沒有任何路徑推進它**（#284 SA Q2 裁示 A：留著
標記不使用）。三態一律經 `enrollment.rules.derive_completion_status` 即時導出——讀那欄
不會報錯，只會讓全班永遠顯示「未開始」，而且週報照樣寄得出去。
"""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.et.constants import COMPLETION_COMPLETED, COMPLETION_IN_PROGRESS, COMPLETION_NOT_STARTED
from app.et.enrollment.rules import derive_completion_status
from app.et.progress.repository import completion_pct

#: `ET_WEEKLY_STAT.AVG_PROGRESS_PCT` / `COMPLETION_RATE` 為 `DECIMAL(5,2)`。
_CENTS = Decimal("0.01")


class CourseStat(NamedTuple):
    """一門課程於某統計日的快照內容（對應 `ET_WEEKLY_STAT` 之六個業務欄位）。"""

    avg_progress_pct: Decimal
    cnt_not_started: int
    cnt_in_progress: int
    cnt_completed: int
    completion_rate: Decimal
    cnt_enrolled: int


def summarize(counts: Mapping[str, tuple[int, int]]) -> CourseStat:
    """由全班的 `{user_id: (完成項目數, 總項目數)}` 導出課程層統計（FR-ET-US14-02）。

    ## 平均進度取「逐學員百分比之平均」，而非「總完成數 ÷ 總項目數」

    也不是精確比值的平均——用的是 `progress.completion_pct`，**與 ET03 頁面顯示每位
    學員進度時同一支**。兩邊各算一份的話，教師把畫面上的數字自己平均會對不上週報，
    而兩個數字都「看起來合理」，沒有人會知道哪個錯。

    ## 母體

    `counts` 的 key 即母體，呼叫端須**已濾掉 `IS_REMOVED`**（`data-model` 之
    `CNT_ENROLLED` 定義為「已加入，不含已移除」，完課率分母同）。本函式不再過濾——
    在此重複一次過濾條件，就等於讓「誰算在內」有兩個定義來源。

    Args:
        counts: `{user_id: (done, total)}`；空 dict（無在籍學員）回全零，不除以零。
    """
    cnt_enrolled = len(counts)
    if cnt_enrolled == 0:
        return CourseStat(Decimal("0.00"), 0, 0, 0, Decimal("0.00"), 0)

    tally = {COMPLETION_NOT_STARTED: 0, COMPLETION_IN_PROGRESS: 0, COMPLETION_COMPLETED: 0}
    pct_total = 0
    for done, total in counts.values():
        tally[derive_completion_status(done=done, total=total)] += 1
        pct_total += completion_pct(done, total)

    return CourseStat(
        avg_progress_pct=_rate(pct_total, cnt_enrolled),
        cnt_not_started=tally[COMPLETION_NOT_STARTED],
        cnt_in_progress=tally[COMPLETION_IN_PROGRESS],
        cnt_completed=tally[COMPLETION_COMPLETED],
        completion_rate=_rate(tally[COMPLETION_COMPLETED] * 100, cnt_enrolled),
        cnt_enrolled=cnt_enrolled,
    )


def progress_delta(current: Decimal, previous: Decimal | None) -> Decimal | None:
    """本次與前一次快照之平均進度差；無前次快照回 `None`（AC 5 之「—」）。

    ⚠️ **回 `None` 而不是 `Decimal(0)`**：後者會讓「沒有比較基準」與「與上週持平」變成
    同一件事，而週報要求首次統計顯示「—」。

    差值可為**負**且那是正常的——新增章節會讓完課分母變大，全班平均進度隨之下降。
    """
    return None if previous is None else (current - previous).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _rate(numerator: int, denominator: int) -> Decimal:
    """整數比值 → `DECIMAL(5,2)`；`denominator` 由呼叫端保證非零。"""
    return (Decimal(numerator) / Decimal(denominator)).quantize(_CENTS, rounding=ROUND_HALF_UP)
