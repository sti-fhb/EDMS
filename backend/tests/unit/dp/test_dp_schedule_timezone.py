"""排程 cron 以**台灣時間**解讀（#517）。

## 為什麼要另外開一支測試

既有的 `test_dp_schedule_overview.py::test_週報排程實際觸發日為週一` 斷言
`(fire.hour, fire.minute) == (10, 0)`——那**對時區不敏感**，實測兩種設定都通過：

```
timezone=UTC          → next_fire=2026-10-06 10:00:00+00:00  hour=10
timezone=Asia/Taipei  → next_fire=2026-10-06 10:00:00+08:00  hour=10
```

因為 `fire` 帶的是**該時區的牆上時間**，`hour` 永遠等於 cron 的小時欄位。那條斷言釘的是
**cron 欄位值**，不是實際觸發時刻——所以引擎從 UTC 改成台北（或改回去）它都不會變紅。
這也是「5 支排程晚 8 小時觸發」能活到現在的原因。

## 本檔的斷言方式

一律換算成 **UTC 絕對時刻**再比對。那是唯一分得出兩種設定的寫法：

| cron | 台灣時間 | UTC 絕對時刻 |
|---|---|---|
| `0 8 * * *` | 每日 08:00 | **00:00** |
| `0 10 * * 0` | 週一 10:00 | **02:00**（週一）|

寫 unit 不寫 integration：拿掉真 DB 也驗得了（純 `CronTrigger` 行為）。

⛔ **本檔每一條都必須在引擎設為 UTC 時變紅。** 初稿曾有一條
`test_週報觸發於台灣時間週一而非週二`，斷言 `0 10 * * 0` 的 `weekday()` 在台灣與 UTC 兩側
皆為 0——它在**修之前就是綠的**（台灣 10:00 與 UTC 10:00 都落在週一），對時區毫無鑑別力，
而 docstring 卻宣稱它「守時區換算後的日界」。已刪除；日界由下方
`test_跨UTC日界的cron不會被算錯日期` 承擔，那條用的是**會跨日**的時刻（台灣週一 02:00 ＝
UTC 週日 18:00），兩種設定給出不同的星期。
"""

from datetime import timezone

import pytest

from app.dp.schedules.scheduler import next_run

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("cron_expr", "taipei_desc", "expected_utc_hour"),
    [
        ("0 8 * * *", "每日 08:00", 0),
        ("0 10 * * 0", "週一 10:00", 2),
        ("30 17 * * *", "每日 17:30", 9),
    ],
)
def test_cron以台灣時間解讀(cron_expr: str, taipei_desc: str, expected_utc_hour: int) -> None:
    """cron 字面值即台灣時間；換算成 UTC 絕對時刻後必須符合預期。

    ⛔ 不可改成斷言 `fire.hour == <cron 的小時>`——那在任何時區設定下都成立，等於沒驗。
    """
    fire = next_run(cron_expr)

    assert fire is not None, f"{cron_expr} 無法解析"
    in_utc = fire.astimezone(timezone.utc)
    assert in_utc.hour == expected_utc_hour, (
        f"{cron_expr}（{taipei_desc} 台灣時間）應於 UTC {expected_utc_hour:02d}:xx 觸發，"
        f"實際為 UTC {in_utc:%H:%M}——引擎可能仍以 UTC 解讀 cron"
    )


def test_跨UTC日界的cron不會被算錯日期() -> None:
    """台灣時間週一 07:00 ＝ UTC **週日** 23:00——日界確實會位移，本條釘住這件事。

    ⚠️ **刻意用 `0 7 * * 0` 而非更極端的 `0 2 * * 0`**：後者沒有人會設，證明了機制卻沒釘住
    任何人真的會踩到的東西。07:00 是「排在上班前，一來就看到」的真實動機所在，而且它距
    SCHET001 現行的 `0 10 * * 0` 只有 3 小時——管理者往前挪一下就到了。

    搭配 `tests/integration/et/test_et_schet001_stats.py::TestSnapshotDateIsTaipei`：那邊驗
    這個時刻寫出的 `STAT_DATE` 仍是台灣日期；這邊驗時刻本身確實落在 UTC 的前一天。
    兩條合起來才完整——只有這條的話，看得到日界位移卻看不出它會造成什麼。
    """
    fire = next_run("0 7 * * 0")

    assert fire is not None
    assert fire.weekday() == 0, "台灣時間應為週一"
    assert fire.astimezone(timezone.utc).weekday() == 6, "台灣週一 07:00 在 UTC 是週日"
