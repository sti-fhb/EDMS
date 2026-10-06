"""ET 學習追蹤 CSV 的時間欄位以台灣時間輸出（#519 第 2 項）。

`_fmt_dt` 供三個匯出欄位使用（`service.py` 的 `joined_at` / `last_activity_at` / `submitted_at`），
原本直接對 `TIMESTAMPTZ` 取出的值 `strftime`——asyncpg 解碼回的恆為 UTC aware datetime，
於是匯出檔寫的是 UTC 牆上時間，而同一列在 `StudentListBlock.tsx` 畫面上走 `formatDateTime`
（瀏覽器本地＝台灣），**同一筆資料兩邊差 8 小時**。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.et.tracking.service import _fmt_dt

pytestmark = pytest.mark.unit

#: 台灣 2026-10-01 07:30（UTC 為前一日 23:30）。
#: 刻意落在**台灣 00:00–08:00** 這段——只有在這 8 小時內 UTC 與台灣才會跨日，
#: 取中午的時點會讓「有換算」與「沒換算」輸出同一個日期，測試即失去鑑別力。
_CROSS_DAY_UTC = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)


def test_匯出時間以台灣時間輸出():
    """跨日時點：輸出必須是台灣的 10/01 07:30，不是 UTC 的 09/30 23:30。"""
    taipei = "2026-10-01 07:30"
    utc = "2026-09-30 23:30"

    assert taipei != utc, "時點設計失誤：兩者相同則本測試無鑑別力"

    rendered = _fmt_dt(_CROSS_DAY_UTC)

    assert rendered == taipei
    assert rendered != utc


def test_已是台灣時區的輸入不再偏移():
    """輸入若已帶 +08:00，`astimezone` 不應再加一次 8 小時。"""
    taipei_aware = datetime(2026, 10, 1, 7, 30, tzinfo=timezone(timedelta(hours=8)))

    assert _fmt_dt(taipei_aware) == "2026-10-01 07:30"


def test_None_仍回破折號():
    """空值的呈現是畫面契約的一部分（空字串會讓儲存格看起來像漏資料），不可因改時區而變。"""
    assert _fmt_dt(None) == "—"
