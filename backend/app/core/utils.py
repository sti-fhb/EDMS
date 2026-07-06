"""核心工具函式。"""

from datetime import datetime, timezone


def escape_like(value: str) -> str:
    """跳脫 SQL LIKE 萬用字元（% 和 _），防止使用者輸入干擾搜尋語意。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def utcnow() -> datetime:
    """回傳目前 UTC 時間（aware datetime，tzinfo=timezone.utc）。

    全系統時間基準：DB 欄位使用 TIMESTAMPTZ、Python 端傳 aware datetime，
    不依賴 OS / DB server / Docker 的 timezone 設定。
    """
    return datetime.now(timezone.utc)
