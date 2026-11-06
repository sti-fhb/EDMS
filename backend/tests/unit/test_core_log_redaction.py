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


# ---- 值出現在 DB 錯誤主訊息裡（#905 B10）----
# 訊息原文取自 2026-11-04 對 PostgreSQL 17 + asyncpg 實測；真實格式另由
# tests/integration/test_core_log_redaction_db.py 釘住，防升級後格式漂移。

_ID = "A123456789"


def _headers(out: str) -> str:
    """只取每層例外的「型別: 訊息」標頭行。

    堆疊會印出原始碼行，而 `raise X("…")` 那一行本身就含測試寫的字面——正向斷言比對整段輸出的話，
    訊息被遮掉也照樣通過（變異檢查實際抓到過）。
    """
    return "\n".join(line for line in out.splitlines() if not line.startswith(" "))


def _wrap_db_error(orig: Exception) -> Exception:
    """把驅動層例外包成 SQLAlchemy 的 DBAPIError，鏈與正式環境相同（`raise … from orig`）。"""
    from sqlalchemy.exc import DBAPIError

    try:
        raise DBAPIError.instance(
            statement="SELECT CAST($1 AS integer)", params=(_ID,), orig=orig, dbapi_base_err=Exception
        ) from orig
    except DBAPIError as exc:
        return exc


def _pg_error(message: str) -> Exception:
    """PostgreSQL 伺服端解析失敗（值在主訊息、不在 DETAIL）。"""
    import asyncpg.exceptions as pg_exc

    return _wrap_db_error(pg_exc.InvalidTextRepresentationError(message))


def _asyncpg_argument_error() -> Exception:
    """asyncpg 用戶端編碼參數失敗：值出現在 DataError 與鏈上的根因兩處。"""
    import asyncpg.exceptions as pg_exc

    reason = f"invalid UUID '{_ID}': length must be between 32..36 characters, got 10"
    try:
        try:
            raise ValueError(reason)
        except ValueError as codec_error:
            raise pg_exc.DataError(f"invalid input for query argument $1: '{_ID}' ({reason})") from codec_error
    except pg_exc.DataError as orig:
        return _wrap_db_error(orig)


@pytest.mark.parametrize(
    ("message", "kept"),
    [
        (f'invalid input syntax for type integer: "{_NAME}{_ID}"', "invalid input syntax for type integer"),
        (f'invalid input syntax for type uuid: "{_ID}"', "type uuid"),
        (f'date/time field value out of range: "{_ID}"', "date/time field value out of range"),
        (f'value "{_ID}" is out of range for type integer', "is out of range for type integer"),
        (f'malformed array literal: "{_ID}"', "malformed array literal"),
    ],
)
def test_masks_value_in_pg_primary_message(message, kept):
    """PG 把輸入值放在主訊息（不是 DETAIL）時，值要遮掉，錯誤種類與型別名要留著。"""
    exc = _pg_error(message)
    assert _ID in str(exc).split("[SQL:")[0]  # 基準：主訊息確實帶值（[parameters:] 那份不算）

    out = format_exception_for_log(exc)
    assert _ID not in out
    assert _NAME not in out
    assert kept in _headers(out)


def test_masks_asyncpg_argument_value_across_chain():
    """asyncpg 編碼參數失敗：值在 DataError 與根因 ValueError 各出現一次，兩處都要遮。"""
    out = format_exception_for_log(_asyncpg_argument_error())
    assert _ID not in out
    assert "invalid input for query argument $1" in _headers(out)  # 看得出是第幾個參數
    assert "length must be between 32..36 characters" in _headers(out)  # 根因的說明仍在
    assert "起因於 builtins.ValueError" in _headers(out)


def test_masks_unquoted_asyncpg_argument_repr():
    """非字串參數的 repr 沒有引號（如整數、datetime），`$N:` 之後要整段遮，不能只靠引號。"""
    import asyncpg.exceptions as pg_exc

    out = format_exception_for_log(
        _wrap_db_error(pg_exc.DataError("invalid input for query argument $2: 912345678 (expected str, got int)"))
    )
    assert "912345678" not in out
    assert "invalid input for query argument $2" in _headers(out)


def test_keeps_python_type_names_in_db_error_chain():
    """根因常見的 `'str' object …` 是型別名，不是值，保留才看得出傳錯了什麼型別。"""
    import asyncpg.exceptions as pg_exc

    try:
        try:
            raise TypeError("'str' object cannot be interpreted as an integer")
        except TypeError as codec_error:
            raise pg_exc.DataError(f"invalid input for query argument $1: '{_ID}' (…)") from codec_error
    except pg_exc.DataError as orig:
        out = format_exception_for_log(_wrap_db_error(orig))
    assert "'str' object cannot be interpreted as an integer" in _headers(out)
    assert _ID not in out


@pytest.mark.parametrize(
    "message",
    [
        'duplicate key value violates unique constraint "UQ_DP_USER_EMAIL"',
        'relation "DP_USER" does not exist',
        'column "EMAIL" of relation "DP_USER" does not exist',
        'index "IX_DP_USER_EMAIL" contains unexpected zero page',
    ],
)
def test_keeps_identifier_names_in_db_error(message):
    """約束名、表名、欄位名、索引名是排查線索（且屬 schema、不是個資），不遮。"""
    out = format_exception_for_log(_pg_error(message))
    assert _headers(out).count(message) == 2  # 包裝層與驅動層各一份，兩層都要保留


def test_keeps_driver_class_path_in_sqlalchemy_prefix():
    """SQLAlchemy 前綴 `<class 'asyncpg.exceptions.X'>` 的引號內是類別路徑，不是值。"""
    import asyncpg.exceptions as pg_exc

    orig = pg_exc.InvalidTextRepresentationError(f"<class 'asyncpg.exceptions.DataError'>: x: \"{_ID}\"")
    out = format_exception_for_log(_wrap_db_error(orig))
    assert "<class 'asyncpg.exceptions.DataError'>" in _headers(out)
    assert _ID not in out


def test_masks_value_containing_quote_to_end_of_line():
    """PG 不跳脫值裡的雙引號；只遮到第一個引號會漏出後半段，要遮到該行最後一個引號。"""
    out = format_exception_for_log(_pg_error(f'invalid input syntax for type integer: "ab"{_ID}"'))
    assert _ID not in out


def test_masks_rest_when_quote_unclosed():
    """引號沒有閉合（訊息被截斷）時，從開引號起整段遮掉。"""
    out = format_exception_for_log(_pg_error(f'invalid input syntax for type integer: "{_ID}'))
    assert _ID not in out


def test_masks_multiline_value():
    """值含換行（備註、地址誤傳進 int 欄位）時，PG 照原樣放進主訊息；換行後的部分也要遮。"""
    out = format_exception_for_log(_pg_error(f'invalid input syntax for type integer: "第一行\n{_ID}"'))
    assert _ID not in out


def test_sql_tail_still_truncated_when_main_message_has_value():
    """值的遮罩只做到 `[SQL:` 之前；SQL 本文的引號若一起參與「遮到最後一個引號」，
    `[SQL:` 會被卷進遮罩、之後的截斷與「已遮罩」標記都失效。"""
    import asyncpg.exceptions as pg_exc
    from sqlalchemy.exc import DBAPIError

    orig = pg_exc.InvalidTextRepresentationError(f'invalid input syntax for type integer: "{_ID}"')
    try:
        raise DBAPIError.instance(
            statement='SELECT * FROM "DP_USER" WHERE "USER_ID" = $1 AND "NOTE" = \'x\'',
            params=("p",),
            orig=orig,
            dbapi_base_err=Exception,
        ) from orig
    except DBAPIError as exc:
        out = format_exception_for_log(exc)
    assert "[敏感內容已遮罩]" in _headers(out)
    assert "sqlalche.me" not in out


def test_statement_error_counts_as_db_error():
    """bind processor 失敗時 SQLAlchemy 拋 StatementError 本體（不是 DBAPIError），主訊息同樣帶值。"""
    from sqlalchemy.exc import StatementError

    try:
        raise StatementError(f"invalid literal for int() with base 10: '{_ID}'", "SELECT 1", (), ValueError("x"))
    except StatementError as exc:
        out = format_exception_for_log(exc)
    assert _ID not in out


def test_long_value_masked_in_linear_time():
    """遮罩在 logger.exception() 當下同步執行；長值不能讓耗時隨長度平方成長（舊寫法 4 萬字約 8.5 秒）。"""
    import time

    value = "a" * 200_000
    started = time.perf_counter()
    out = format_exception_for_log(_pg_error(f'invalid input syntax for type integer: "{value}"'))
    assert time.perf_counter() - started < 2
    assert value not in out


def test_non_db_exception_quotes_untouched():
    """非 DB 例外不套用：檔案路徑等引號內容是排查線索，誤遮會讓一般錯誤無從追查。"""
    out = format_exception_for_log(FileNotFoundError(2, "No such file or directory", "/data/dm/x.pdf"))
    assert "'/data/dm/x.pdf'" in _headers(out)


def test_outer_wrapper_of_db_error_also_masked():
    """例外鏈上有 DB 錯誤時，整條鏈都套用：包裝者常把根因訊息接進自己的訊息。"""
    db_error = _pg_error(f'invalid input syntax for type integer: "{_ID}"')
    try:
        raise RuntimeError(f"匯入失敗：'{_ID}'") from db_error
    except RuntimeError as exc:
        out = format_exception_for_log(exc)
    assert _ID not in out
    assert "匯入失敗" in _headers(out)


def test_redact_exception_message_applies_db_rules():
    """`redact_exception_message` 給「把例外訊息寫進 DB／印到 CLI」的呼叫端用，規則與 log 相同。"""
    from app.core.log_redaction import redact_exception_message

    out = redact_exception_message(_asyncpg_argument_error())
    assert _ID not in out
    assert "invalid input for query argument $1" in _headers(out)


def test_redact_exception_message_keeps_non_db_message():
    """非 DB 例外只套用既有規則（Email／JWT 等），其餘原樣。"""
    from app.core.log_redaction import redact_exception_message

    assert redact_exception_message(ValueError("HANDLER_REF 不在允許命名空間內：'x.y'")) == (
        "HANDLER_REF 不在允許命名空間內：'x.y'"
    )


def test_db_error_detected_beyond_output_chain_limit():
    """輸出只印鏈上 4 層，但判定要走更深：DB 錯誤包了 4 層以上，外層轉述的值照樣要遮。"""
    current: BaseException = _pg_error(f'invalid input syntax for type integer: "{_ID}"')
    for depth in range(5):
        try:
            raise RuntimeError(f"第 {depth} 層：'{_ID}'") from current
        except RuntimeError as exc:
            current = exc
    out = format_exception_for_log(current)
    assert _ID not in out


def test_db_error_detected_via_context_when_cause_present():
    """`__cause__` 與 `__context__` 都有時，DB 錯誤在 `__context__` 那一側也要認得出來。"""
    db_error = _pg_error(f'invalid input syntax for type integer: "{_ID}"')
    try:
        try:
            raise db_error
        except Exception:
            raise RuntimeError(f"轉述：'{_ID}'") from ValueError("無關的 cause")
    except RuntimeError as exc:
        out = format_exception_for_log(exc)
    assert _ID not in out


def test_masks_asyncpg_interface_error_argument():
    """編碼器自己拋 InterfaceError 時，asyncpg 改寫成 `query argument $N: …`，沒有 `invalid input for` 前綴。"""
    import asyncpg.exceptions as pg_exc

    out = format_exception_for_log(_wrap_db_error(pg_exc.InterfaceError(f"query argument $1: {_ID} raw")))
    assert _ID not in out
    assert "query argument $1" in _headers(out)


def test_multiline_detail_fully_removed():
    """值含換行時 DETAIL 會跨多行、續行沒有 `DETAIL:` 前綴；從 DETAIL 起到 `[SQL:` 為止都要刪。"""
    import asyncpg.exceptions as pg_exc

    orig = pg_exc.UniqueViolationError('duplicate key value violates unique constraint "UQ_ET_COURSE_TITLE"')
    orig.detail = f'Key ("TITLE")=(第一行\n{_ID}) already exists.'
    out = redact_sensitive(str(_wrap_db_error(orig)))
    assert _ID not in out
    assert "UQ_ET_COURSE_TITLE" in out


def test_email_pattern_linear_on_long_input():
    """Email 樣式跑在 logger.exception() 當下：一長串沒有 @ 的字元不能讓耗時隨長度平方成長。"""
    import time

    started = time.perf_counter()
    redact_sensitive("a" * 200_000)
    assert time.perf_counter() - started < 2


def test_email_still_masked_after_length_limit():
    """長度上限不影響一般 Email；本地端超過 64 字元時仍遮住 @ 前最後 64 字元與網域。"""
    assert "wang@example.com" not in redact_sensitive("寄信失敗 wang@example.com")
    long_local = "x" * 100 + "@example.com"
    assert "x" * 65 + "@" not in redact_sensitive(long_local)


# ---- lifespan 啟動／關閉失敗（#905 B11）----
# Starlette 以 `traceback.format_exc()` 組成 lifespan.*.failed 的 message 交給 uvicorn 當訊息本體記錄，
# 不帶 exc_info，所以 install_exception_redaction 管不到；這裡直接驗 uvicorn 收到的那段文字。


async def _run_lifespan_protocol(lifespan) -> tuple[list[dict], BaseException | None]:
    """以 ASGI lifespan 協定驅動 Starlette Router（與 uvicorn 相同的收發），回傳送出的訊息與最終例外。"""
    from starlette.routing import Router

    incoming = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    sent: list[dict] = []

    async def receive() -> dict:
        return next(incoming)

    async def send(message: dict) -> None:
        sent.append(message)

    router = Router(lifespan=lifespan)
    try:
        await router.lifespan({"type": "lifespan", "app": None, "state": {}}, receive, send)
    except BaseException as exc:  # 本 helper 要把例外交回給測試斷言
        return sent, exc
    return sent, None


def _failing_lifespan(phase: str):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        if phase == "startup":
            raise RuntimeError(f"連不上 DB user={_EMAIL} id={_ID}")
        yield
        raise RuntimeError(f"關閉失敗 user={_EMAIL} id={_ID}")

    return lifespan


@pytest.mark.parametrize(
    ("phase", "failed_type"), [("startup", "lifespan.startup.failed"), ("shutdown", "lifespan.shutdown.failed")]
)
async def test_lifespan_failure_message_has_no_original_text(phase, failed_type):
    """交給 uvicorn 的 traceback 文字不含原例外訊息（也不接例外鏈），只剩位置。"""
    from app.core.log_redaction import redact_lifespan_errors

    sent, exc = await _run_lifespan_protocol(redact_lifespan_errors(_failing_lifespan(phase)))

    failed = [m for m in sent if m["type"] == failed_type]
    assert len(failed) == 1
    text = failed[0]["message"]
    assert _EMAIL not in text
    assert _ID not in text
    assert "During handling" not in text and "direct cause" not in text  # 沒有接上原例外
    assert exc is not None  # 失敗仍往外拋，uvicorn 才會以非零結束


async def test_lifespan_failure_baseline_leaks_without_wrapper():
    """基準：不包的話，原例外訊息會整段出現在交給 uvicorn 的文字裡（本修正的存在理由）。"""
    sent, _ = await _run_lifespan_protocol(_failing_lifespan("startup"))
    assert _ID in sent[-1]["message"]


async def test_lifespan_failure_logged_redacted_with_exc_info(caplog):
    """原例外改走帶 exc_info 的 log：位置與型別留得住，個資經 install_exception_redaction 遮掉。"""
    import logging

    from app.core.log_redaction import install_exception_redaction, redact_lifespan_errors

    install_exception_redaction()
    with caplog.at_level(logging.ERROR, logger="app.core.log_redaction"):
        await _run_lifespan_protocol(redact_lifespan_errors(_failing_lifespan("startup")))

    records = [r for r in caplog.records if r.name == "app.core.log_redaction"]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is not None
    assert "builtins.RuntimeError" in record.exc_text
    assert _EMAIL not in record.exc_text
    assert "w***@example.com" in record.exc_text


async def test_lifespan_success_passes_state_through():
    """正常起停不受影響：lifespan 回傳的 state 照樣交給 Starlette。"""
    from contextlib import asynccontextmanager

    from app.core.log_redaction import redact_lifespan_errors

    @asynccontextmanager
    async def lifespan(app):
        yield {"ready": True}

    sent, exc = await _run_lifespan_protocol(redact_lifespan_errors(lifespan))
    assert exc is None
    assert [m["type"] for m in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


# ---- 遮罩本身的耗時上界（#905 B16 security review）----
# 遮罩跑在 logger.exception() 當下、與 event loop 同一條執行緒；有了 event loop watchdog，卡住超過門檻
# 就會重啟程式，所以「特製輸入讓遮罩跑很久」等於可以觸發重啟。


def test_jwt_pattern_linear_on_long_input():
    """`eyJ` 起點的規則原本每個起點都吃到底再回溯，耗時與長度平方成正比（約 80 KB 實測 45 秒）。

    ⚠️ 不用絕對秒數當門檻：這台開發機多個 session 共用，整套並行時同一段輸入實測從 0.45 秒被拖到 6.9 秒，
    絕對門檻會假紅。改量**長度加倍時耗時變成幾倍**——線性約 2、平方約 4；負載同時拖慢兩次量測，比例大致不變。
    各取 3 次最小值，濾掉單次被排程打斷的雜訊。
    """
    import time

    def fastest(text: str) -> float:
        runs = []
        for _ in range(3):
            started = time.perf_counter()
            redact_sensitive(text)
            runs.append(time.perf_counter() - started)
        return min(runs)

    small = fastest("eyJ" * 10_000)
    large = fastest("eyJ" * 20_000)
    assert large / small < 3, (small, large)


def test_jwt_still_masked_after_length_limit():
    assert "eyJzdWIiOiJ1MSJ9" not in redact_sensitive("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.abcdef")


def test_long_exception_message_truncated_before_masking():
    """遮罩前先截斷：所有規則的耗時都有上界，log 也不會被單一例外撐爆。"""
    from app.core.log_redaction import redact_exception_message

    out = redact_exception_message(ValueError("x" * 50_000))
    assert len(out) < 9_000
    assert "已截斷" in out


def test_truncation_does_not_leak_value_cut_at_boundary():
    """截斷點切在引號中間時，未閉合的引號照樣遮到結尾（DB 錯誤鏈）。"""
    message = "x" * 8_180 + f'invalid input syntax for type integer: "{_ID}"'
    out = format_exception_for_log(_pg_error(message))
    assert _ID not in out
