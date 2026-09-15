"""ET 排程之純業務規則（US14 / #325、#317）。

**完全不碰 DB**：結清時機的判定可以純函式表達，故以 unit 涵蓋；integration 只驗接線。
"""

from datetime import datetime, timedelta
from typing import Final

#: 課程視同關閉後，仍允許繼續作答的寬限時數。
#:
#: `spec_us6` 場景 27 保障「關閉當下已在作答的 attempt 仍可完成並計分」，但沒說到什麼
#: 時候為止——#317 要補的正是那個上界。24 小時的取法：本 job 每日執行，故任何一筆
#: attempt 至少會經過一次完整的「關閉後 24 小時」才被結清，而不是取決於「課程剛好在
#: 排程執行前幾秒到期」這種與學員無關的巧合。
SETTLE_GRACE_HOURS: Final = 24


def should_settle(*, closed_since: datetime | None, timed_out: bool, now: datetime) -> bool:
    """該筆逾期未提交的 attempt 是否可以結清了（#317）。

    兩條各自獨立的路徑，任一成立即可結清：

    | 路徑 | 條件 | 針對 |
    |---|---|---|
    | 作答時限已過 | `timed_out` | 限時測驗——時限一到就沒有合法作答時間了，不必再等寬限 |
    | 課程關閉滿寬限期 | `now - closed_since >= 24h` | **不限時測驗**（見下方說明）|

    不限時測驗是本缺口最寬的一側——`is_timed_out` 對它恆為 `False`，少了寬限期這條，
    它永遠不會被結清，等於 #317 沒修。

    ## 為何不是「課程一關就結清」

    那會讓「學員還剩多少合法作答時間」取決於課程訖止時間與排程時點的相對位置：
    07:30 開始一份 60 分鐘測驗、課程 08:00 到期、排程 08:00 執行——學員還有 30 分鐘
    卻被強制交卷，且狀態被記為「逾時」，與事實不符。那正是 `spec_us6` 場景 27 要保障
    的情境，不能被本作業推翻。

    Args:
        closed_since: 課程「視同關閉」的起算時點（手動關閉取 `CLOSED_AT`、期間已過取
            `OPEN_END_AT`）。`None` 表示資料異常（已關閉卻沒有任何時點）——此時
            **允許結清**：一門關閉的課程不該因為缺一個時間戳就讓 attempt 永遠留著。
    """
    if timed_out or closed_since is None:
        return True
    return now - closed_since >= timedelta(hours=SETTLE_GRACE_HOURS)


def needs_urgent_remind(*, open_end_at: datetime, urgent_days: int, already_sent: bool, now: datetime) -> bool:
    """該課程是否應於本次執行寄出加急提醒（FR-ET-US14-07 / FR-ET-US14-08）。

    三個閘各自獨立：

    | 閘 | 條件 | 為何 |
    |---|---|---|
    | 防重複 | `already_sent` 為真則不寄 | `URGENT_REMIND_SENT`；每門課只寄一次，再開課時歸 false 重計 |
    | 已到期 | `now >= open_end_at` 則不寄 | 同一次執行中它已被「到期關閉」處理，再寄「即將截止」是矛盾的 |
    | 窗口 | 距訖止 ≤ `urgent_days` 天才寄 | `DP_PARAM.ET_URGENT_REMIND_DAYS`，預設 3 |

    邊界取 `<=`：「訖止前 3 天」包含剛好整 3 天的當下。取 `<` 會讓訖止時間剛好落在
    執行時點整數天後的課程整批漏寄，而排程是固定時點觸發，這種對齊並不罕見。

    `urgent_days = 0` 因「已到期」閘而等於停用加急提醒（窗口寬度為零，且訖止當下已被
    前一個閘擋下）——這是合理的停用語意，不該變成「全部都寄」。
    """
    if already_sent or now >= open_end_at:
        return False
    return open_end_at - now <= timedelta(days=urgent_days)
