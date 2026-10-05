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
            ⚠️ **只接受 aware**：`astimezone` 對 naive 值會**以執行環境的系統時區**解讀它，
            於是同一筆資料在本機（台灣）與容器（UTC）會換算出不同結果，且兩邊都不報錯。
            本專案 DB 欄位一律 `DateTime(timezone=True)`、取出即 aware，正常路徑不會踩到；
            會踩到的是自行 `datetime(...)` 構造後傳進來——那本身已違反 `sti-backend-modules.md`
            的時間處理規範（一律 `utcnow()`）。

    Returns:
        台灣時間的 `YYYY-MM-DD HH:MM`；`value` 為 None 時回空字串。
    """
    return value.astimezone(_DISPLAY_TZ).strftime("%Y-%m-%d %H:%M") if value else ""


def format_taipei_date(value: datetime | None) -> str:
    """TIMESTAMPTZ 欄位 → 給人看的 `YYYY-MM-DD`（**台灣時間**，只要日期）；None 回空字串。

    與 `format_taipei` 同一次換算、只差輸出格式。**不要改用 `format_taipei(v)[:10]`**——那是對
    格式字串的位置假設，日後若在前面加了前綴或改了格式就會靜默切錯。

    與 `format_taipei` 同樣的陷阱、但後果更隱蔽：只取日期時，UTC 與台灣只在**一天之中的 8 小時**
    （台灣 00:00–08:00）才會不同，所以寫錯的程式有 2/3 的時間是對的。密碼到期提醒信原本直接
    `strftime`，密碼在那個區間變更的使用者會收到早一天的到期日（#513）。

    Args:
        value: 來自 TIMESTAMPTZ 欄位的 aware datetime，或 None。
            ⚠️ 只接受 aware，naive 值的風險同 `format_taipei`（該處有完整說明）。

    Returns:
        台灣時間的 `YYYY-MM-DD`；`value` 為 None 時回空字串。
    """
    return value.astimezone(_DISPLAY_TZ).strftime("%Y-%m-%d") if value else ""
