"""log 去識別化單元測試（#123）。

SQLAlchemy 的 StatementError 系列在 __str__ 時會把 SQL 與**綁定參數**一併附上，
帶個資的 DB 操作若拋出未攔截例外，個資就會原樣寫進 log（違反
.claude/rules/sti-backend-logging.md §禁寫入 log 的敏感資料）。

本測試先以「修正前的基準」斷言個資確實存在於原始例外訊息中（作為回歸護欄），
再驗證去識別化後不再出現、且仍保留可排查資訊。
"""

import re

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.log_redaction import format_exception_for_log, redact_sensitive

pytestmark = pytest.mark.unit

_EMAIL = "wang@example.com"
_NAME = "王小明"


def _db_error() -> IntegrityError:
    """重現帶個資綁定參數的 DB 例外（不需真 DB，直接建構 SQLAlchemy 例外）。"""
    return IntegrityError(
        statement="INSERT INTO DP_USER (EMAIL, USER_NAME)\n VALUES (?, ?)",
        params=(_EMAIL, _NAME),
        orig=Exception("UNIQUE constraint failed: DP_USER.EMAIL"),
    )


def test_baseline_raw_message_contains_pii():
    """修正前基準：原始例外訊息確實含 Email 與姓名（本測試即洩漏來源的存在證明）。"""
    raw = str(_db_error())
    assert _EMAIL in raw
    assert _NAME in raw
    assert "[parameters:" in raw


def test_redacts_sql_and_parameters_sections():
    """去識別化後 [SQL: ...] / [parameters: ...] 區段消失，個資不再出現。"""
    out = redact_sensitive(str(_db_error()))
    assert _EMAIL not in out
    assert _NAME not in out
    assert "[parameters:" not in out
    assert "INSERT INTO DP_USER" not in out


def test_keeps_diagnosable_information():
    """仍保留可排查資訊：驅動層錯誤描述（如違反的約束名）與遮罩標記。"""
    out = redact_sensitive(str(_db_error()))
    assert "UNIQUE constraint failed: DP_USER.EMAIL" in out
    assert "已遮罩" in out


def test_masks_email_outside_sql_section():
    """縱深防禦：區段外（如 driver 的 DETAIL 行）出現的 Email 亦遮罩，網域保留供排查。"""
    out = redact_sensitive(f"duplicate key value violates unique constraint DETAIL: Key (email)=({_EMAIL}) exists")
    assert _EMAIL not in out
    assert "@example.com" in out
    assert "***" in out


def test_plain_message_unchanged():
    """無敏感樣式的訊息不應被改寫（避免遮罩邏輯污染一般錯誤訊息）。"""
    assert redact_sensitive("connection reset by peer") == "connection reset by peer"


def test_format_exception_keeps_type_and_location():
    """格式化輸出含例外型別與發生位置（檔案 / 行號），供線上排查。"""
    try:
        raise KeyError("missing_key")
    except KeyError as exc:
        out = format_exception_for_log(exc)
    assert "KeyError" in out
    assert "test_core_log_redaction.py" in out
    assert re.search(r"line \d+", out)


def test_format_exception_redacts_db_parameters():
    """DB 例外經格式化後不含個資，但含型別與堆疊。"""
    try:
        raise _db_error()
    except IntegrityError as exc:
        out = format_exception_for_log(exc)
    assert _EMAIL not in out
    assert _NAME not in out
    assert "IntegrityError" in out
    assert "test_core_log_redaction.py" in out


def test_format_exception_without_traceback():
    """未經 raise 的例外（無 traceback）不應炸掉格式化。"""
    out = format_exception_for_log(ValueError("boom"))
    assert "ValueError" in out
    assert "boom" in out
