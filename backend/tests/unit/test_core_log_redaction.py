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


def test_redacts_asyncpg_detail_line():
    """asyncpg 的 DETAIL 行含 `Key (欄位)=(值)`，位置在 [SQL: 之前，必須另外移除。

    asyncpg PostgresError.__str__ 會接上 DETAIL / HINT（asyncpg/exceptions/_base.py），
    SQLAlchemy 再以 str(orig) 併入包裝例外的訊息本體。
    """
    import asyncpg.exceptions as pg_exc
    from sqlalchemy.exc import DBAPIError

    orig = pg_exc.UniqueViolationError('duplicate key value violates unique constraint "DP_USER_USER_NAME_KEY"')
    orig.detail = f"Key (USER_NAME)=({_NAME}) already exists."
    wrapped = DBAPIError.instance(
        statement="INSERT INTO DP_USER (EMAIL, USER_NAME) VALUES ($1, $2)",
        params=(_EMAIL, _NAME),
        orig=orig,
        dbapi_base_err=Exception,
    )

    assert _NAME in str(wrapped)  # 修正前基準：DETAIL 行確實帶出姓名
    out = redact_sensitive(str(wrapped))
    assert _NAME not in out
    assert _EMAIL not in out
    assert "DP_USER_USER_NAME_KEY" in out  # 仍看得出違反哪個約束


def test_masks_pydantic_input_value():
    """Pydantic ValidationError 會 echo 觸發失敗的原始輸入（可能是密碼 / PARAM_VALUE）。"""
    from pydantic import BaseModel, Field, ValidationError

    class _Model(BaseModel):
        name: str = Field(max_length=3)

    secret = "pbkdf2$sha256$verysecrethash"
    try:
        _Model(name=secret)
    except ValidationError as exc:
        out = redact_sensitive(str(exc))
    assert secret not in out
    assert "input_value=[已遮罩]" in out
    assert "string_too_long" in out  # 仍看得出是哪種驗證失敗


def test_masks_jwt_like_token():
    """JWT 原始值屬禁寫入 log 之敏感資料，僅保留前 8 碼供比對。"""
    out = redact_sensitive("token decode failed for eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.abcdef")
    assert "eyJzdWIiOiJ1MSJ9" not in out
    assert "eyJhbGci***" in out


def test_truncates_sql_tail_even_with_bracket_in_statement():
    """statement 內含「換行後接 [」時仍整段截掉（逐段 lookahead 會提前收手、殘留尾段）。"""
    statement = """UPDATE T SET DATA = '
[1,2]', SECRET='hunter2'"""
    out = redact_sensitive(str(IntegrityError(statement=statement, params=("x",), orig=Exception("boom"))))
    assert "hunter2" not in out
    assert "[1,2]" not in out
    assert "boom" in out


def test_format_exception_keeps_root_cause():
    """包裝型例外要保留鏈上根因，否則只剩外層訊息、查不出真正失敗原因。"""
    try:
        try:
            raise _db_error()
        except IntegrityError as inner:
            raise RuntimeError("建立使用者失敗") from inner
    except RuntimeError as exc:
        out = format_exception_for_log(exc)

    assert "RuntimeError" in out
    assert "建立使用者失敗" in out
    assert "起因於" in out
    assert "IntegrityError" in out
    assert "UNIQUE constraint failed: DP_USER.EMAIL" in out  # 根因的約束名保留
    assert _EMAIL not in out
    assert _NAME not in out


def test_format_exception_includes_group_members():
    """ExceptionGroup（anyio / TaskGroup）只印外層會失去真正原因，需展開子例外。"""
    try:
        raise ExceptionGroup("多個背景任務失敗", [ValueError("壞值"), KeyError("missing")])
    except BaseExceptionGroup as exc:
        out = format_exception_for_log(exc)
    assert "ValueError" in out
    assert "KeyError" in out
