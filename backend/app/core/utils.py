"""核心工具函式。"""

from datetime import datetime, timezone
from typing import Final
from zoneinfo import ZoneInfo

#: 使用者可見時間之呈現時區。EDMS 為單一組織、單一院區，不做逐使用者時區。
#: 與 `app/et/notify/course_invite.py::_DISPLAY_TZ`、`frontend/src/utils/date.ts` 同一基準。
_DISPLAY_TZ: Final = ZoneInfo("Asia/Taipei")


def escape_like(value: str) -> str:
    """跳脫 SQL LIKE 萬用字元（% 和 _），防止使用者輸入干擾搜尋語意。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def utcnow() -> datetime:
    """回傳目前 UTC 時間（aware datetime，tzinfo=timezone.utc）。

    全系統時間基準：DB 欄位使用 TIMESTAMPTZ、Python 端傳 aware datetime，
    不依賴 OS / DB server / Docker 的 timezone 設定。
    """
    return datetime.now(timezone.utc)


def format_taipei(value: datetime | None) -> str:
    """TIMESTAMPTZ 欄位 → 給人看的 `YYYY-MM-DD HH:MM`（**台灣時間**）；None 回空字串。

    ⚠️ **不可直接對 DB 取出的值做 `strftime`**：asyncpg 解碼 `timestamptz` 回的是 **UTC aware**
    datetime，`strftime` 取的是它的 UTC 牆上時間、而且不帶任何時區標示。DM03 / DM05 的稽核 CSV
    原本就是這樣寫的，台灣時間 10/01 07:30 的事件在檔案裡變成 `2026-09-30 23:30`——對所有使用者
    皆錯，且與同頁以台灣時間切日的日期篩選自相矛盾（#483）。

    Args:
        value: 來自 TIMESTAMPTZ 欄位的 aware datetime，或 None。

    Returns:
        台灣時間的 `YYYY-MM-DD HH:MM`；`value` 為 None 時回空字串。
    """
    return value.astimezone(_DISPLAY_TZ).strftime("%Y-%m-%d %H:%M") if value else ""
