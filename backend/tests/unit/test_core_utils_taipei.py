"""`format_taipei` 單元測試（#483 security review LOW-3 延伸）。

DM03 / DM05 的稽核 CSV 原本直接對 asyncpg 回傳的 datetime 做 `strftime`。那個物件是 **UTC
aware**，`strftime` 取的是它的 UTC 牆上時間、且不帶任何時區標示——台灣時間 10/01 07:30 的
事件在 CSV 裡寫成 `2026-09-30 23:30`。這對**所有**使用者都是錯的（不限國外時區），而且與
同頁已改為台灣時間日界的日期篩選互相矛盾：篩 10/01 撈出來的那筆，CSV 卻寫 09/30。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.utils import format_taipei

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
