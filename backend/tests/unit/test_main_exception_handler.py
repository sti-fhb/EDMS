"""全域 500 handler 的 log 內容測試（#123）。

驗證未攔截的 DB 例外落到 unhandled_exception_handler 時，log 不再出現個資，
且仍保留例外型別、發生位置與請求的 method / path。
"""

import logging

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from main import unhandled_exception_handler

pytestmark = pytest.mark.unit

_EMAIL = "wang@example.com"
_NAME = "王小明"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("test", 80),
            "path": "/api/register",
            "query_string": b"",
            "headers": [],
        }
    )


async def test_log_excludes_pii_but_keeps_diagnostics(caplog):
    """帶個資參數的未攔截 DB 例外：log 不含 Email / 姓名，仍含型別、位置與請求資訊。"""
    try:
        raise IntegrityError(
            statement="INSERT INTO DP_USER (EMAIL, USER_NAME) VALUES (?, ?)",
            params=(_EMAIL, _NAME),
            orig=Exception("UNIQUE constraint failed: DP_USER.EMAIL"),
        )
    except IntegrityError as exc:
        with caplog.at_level(logging.ERROR):
            resp = await unhandled_exception_handler(_request(), exc)

    text = caplog.text
    assert _EMAIL not in text
    assert _NAME not in text
    assert "[parameters:" not in text
    assert "IntegrityError" in text
    assert "POST" in text
    assert "/api/register" in text
    assert "test_main_exception_handler.py" in text
    assert resp.status_code == 500


async def test_response_body_unchanged(caplog):
    """對外回應維持通用 500（不洩漏內部細節）。"""
    with caplog.at_level(logging.ERROR):
        resp = await unhandled_exception_handler(_request(), RuntimeError("boom"))
    assert resp.status_code == 500
    assert b"COMMON_500" in resp.body
    assert b"Internal Server Error" in resp.body
