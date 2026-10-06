"""`format_taipei` 單元測試（#483 security review LOW-3 延伸）。

DM03 / DM05 的稽核 CSV 原本直接對 asyncpg 回傳的 datetime 做 `strftime`。那個物件是 **UTC
aware**，`strftime` 取的是它的 UTC 牆上時間、且不帶任何時區標示——台灣時間 10/01 07:30 的
事件在 CSV 裡寫成 `2026-09-30 23:30`。這對**所有**使用者都是錯的（不限國外時區），而且與
同頁已改為台灣時間日界的日期篩選互相矛盾：篩 10/01 撈出來的那筆，CSV 卻寫 09/30。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.utils import format_taipei, taipei_day_start

pytestmark = pytest.mark.unit

_TAIPEI_OFFSET = timezone(timedelta(hours=8))


def test_utc_aware_轉為台灣時間():
    """asyncpg 給的是 UTC aware——必須換算後再格式化，不能直接 strftime。"""
    value = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)

    assert format_taipei(value) == "2026-10-01 07:30"


def test_跨日的那一刻():
    """UTC 仍是前一天、台灣已跨日：這正是稽核 CSV 與日期篩選對不起來的區間。"""
    assert format_taipei(datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)) == "2026-10-01 00:00"
    assert format_taipei(datetime(2026, 9, 30, 15, 59, tzinfo=timezone.utc)) == "2026-09-30 23:59"


def test_已是台灣時區的值不重複換算():
    """輸入帶 +08:00 時應原樣呈現，不可再加 8 小時。"""
    assert format_taipei(datetime(2026, 10, 1, 7, 30, tzinfo=_TAIPEI_OFFSET)) == "2026-10-01 07:30"


def test_none_回空字串():
    """欄位可為 NULL（如尚未廢止）；CSV 該格留空而非 'None'。"""
    assert format_taipei(None) == ""


def test_with_seconds_輸出到秒():
    """稽核匯出需要秒（#519）：同一分鐘內的多筆事件若降精度到分，先後順序就消失了。"""
    value = datetime(2026, 9, 30, 23, 30, 45, tzinfo=timezone.utc)

    assert format_taipei(value, with_seconds=True) == "2026-10-01 07:30:45"


def test_with_seconds_預設為關閉():
    """既有兩個呼叫端（DM03 / DM05 的 CSV）不帶此參數，輸出必須與 #483 當時完全相同。

    ⚠️ 本條是**既有行為的護欄**：`with_seconds` 若被改成預設 True，那兩支 CSV 會默默多出秒數。
    """
    value = datetime(2026, 9, 30, 23, 30, 45, tzinfo=timezone.utc)

    assert format_taipei(value) == "2026-10-01 07:30"
    assert format_taipei(value, with_seconds=False) == "2026-10-01 07:30"


def test_with_seconds_為_keyword_only():
    """禁止 `format_taipei(v, True)` 這種位置呼叫——讀的人看不出 True 是什麼意思。"""
    value = datetime(2026, 9, 30, 23, 30, 45, tzinfo=timezone.utc)

    with pytest.raises(TypeError):
        format_taipei(value, True)  # 刻意的錯誤呼叫，驗 keyword-only 真的擋得住


def test_with_seconds_的_none_仍回空字串():
    """空值分支不該因為多了參數而改變。"""
    assert format_taipei(None, with_seconds=True) == ""


def test_日界起點為台灣午夜而非_utc_午夜():
    """查詢邊界用（#519）：台灣 10/01 的起點是 UTC 的 09/30 16:00，不是 UTC 的 10/01 00:00。

    兩者差 8 小時，而那 8 小時正是「使用者選 10/01 卻撈不到當天凌晨紀錄」的區間。
    """
    start = taipei_day_start(date(2026, 10, 1))

    assert start.isoformat() == "2026-10-01T00:00:00+08:00"
    assert start.astimezone(timezone.utc) == datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
    assert start != datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), "退回 UTC 午夜即為本條要擋的回歸"


def test_日界上界為隔日台灣午夜():
    """`date_to` 須含當日全天，故上界取隔日 00:00 並以 `<` 比對。"""
    upper = taipei_day_start(date(2026, 10, 1), plus_days=1)

    assert upper.isoformat() == "2026-10-02T00:00:00+08:00"
    assert upper - taipei_day_start(date(2026, 10, 1)) == timedelta(days=1)


def test_日界跨月跨年不出錯():
    """`+timedelta(days=1)` 的邊界：月底與年底。"""
    assert taipei_day_start(date(2026, 1, 31), plus_days=1).isoformat() == "2026-02-01T00:00:00+08:00"
    assert taipei_day_start(date(2026, 12, 31), plus_days=1).isoformat() == "2027-01-01T00:00:00+08:00"
