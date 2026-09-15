"""ET03 學員學習狀況追蹤之純業務規則（US9 / #322）。

集中於此而非散在 service：這些判定不需 DB、可獨立以 unit test 驗證。

**完課三態不在本檔**——沿用 `enrollment/rules.derive_completion_status`。US9 與 ET04
「我的課程」看的是同一件事，兩份實作遲早分岔，而分岔的表現是「同一位學員在教師頁顯示
進行中、在自己頁顯示已完成」。
"""


def can_reset_retry(*, used: int, max_retry: int, is_passed: bool, has_attempt: bool) -> bool:
    """教師是否可重置該學員於該測驗之重考次數（FR-ET-US9-06）。

    ## ⚠️ 「次數用盡」是 `used > max_retry`，不是 `used >= max_retry`

    總可作答次數 = **`MAX_RETRY + 1`**（`attempt/rules.can_start_attempt` 明訂
    `MAX_RETRY = 0` 是「只能作答 1 次」而非「不能作答」）。用 `>=` 會讓學員**還剩最後
    一次**時教師就看到可點的重置按鈕——按下去等於白送一輪配額，而畫面上看不出哪裡不對。

    ## 三種「不可重置」的理由各自獨立

    | 條件 | 為何不給重置 |
    |---|---|
    | 未作答（`has_attempt=False`）| 配額原本就是滿的，「重置」無從談起 |
    | 已及格 | 他已經通過了；再考只有機會把成績弄低 |
    | 次數未用盡 | 學員自己還能重考，不需要教師介入 |

    已及格與次數用盡**會同時成立**（最後一次才及格），此時仍不可重置——故三者是
    `and` 的關係，不能寫成擇一判斷。

    `used` 應為**本輪**已用次數（`attempt/rules.round_used_attempts` 的輸出，已扣掉
    先前重置的基準），不是 attempt 總數。

    Args:
        used: 本輪已用作答次數。
        max_retry: 該測驗之重考次數上限（總配額為此值 + 1）。
        is_passed: 該學員於該測驗是否曾及格。
        has_attempt: 該學員於該測驗是否有任何 attempt。

    Returns:
        可重置為 `True`。
    """
    if not has_attempt or is_passed:
        return False
    return used > max_retry
