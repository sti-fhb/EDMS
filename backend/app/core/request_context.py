"""Request Context — 使用 contextvars 存放 request 層級資訊。

目前用途：自動記錄 client IP，
讓後續稽核日誌（log_action()）不需要每個呼叫端手動傳入 ip_address。
"""

from contextvars import ContextVar
from typing import Optional

_client_ip: ContextVar[Optional[str]] = ContextVar("_client_ip", default=None)


def get_client_ip() -> Optional[str]:
    """取得當前 request 的 client IP（由 middleware 設定）。"""
    return _client_ip.get()


def set_client_ip(ip: Optional[str]) -> None:
    """設定當前 request 的 client IP（由 middleware 呼叫）。"""
    _client_ip.set(ip)
