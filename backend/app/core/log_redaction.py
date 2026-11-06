"""log 去識別化工具（#123）。

SQLAlchemy 的 `StatementError` 系列（`IntegrityError` / `DataError` /
`OperationalError` …）在 `__str__` 時會把 SQL 與**綁定參數**一併附上；PostgreSQL
（asyncpg）另會在訊息本體接上 `DETAIL:` / `HINT:` 行，其中的 `Key (欄位)=(值)`
直接含欄位值。因此帶個資的 DB 操作若拋出未攔截例外，該筆個資會原樣寫進 log——
log 的流向通常比 DB 寬鬆（複製到開發機、送入收集服務、貼上通訊軟體），個資因此
離開受控環境。違反 `.claude/rules/sti-backend-logging.md` §禁寫入 log 的敏感資料。

設計取捨：**不以「不記 traceback」換取安全**（線上問題會無法追查），而是
1. 從 `[SQL:` 起整段截掉（`[SQL: …]` / `[parameters: …]` 與說明連結皆在其後）
2. 移除 asyncpg 追加的 `DETAIL:` / `HINT:` / `CONTEXT:` 行
3. 遮罩 Pydantic `ValidationError` 的 `input_value=…`（會 echo 密碼 / 參數值）
4. 遮罩 Email 與 JWT 樣式字串
5. 以「例外型別 + 遮罩後訊息 + `traceback.format_tb` 堆疊」表達位置——`format_tb`
   只輸出檔案 / 行號 / 原始碼行，不含例外訊息、不含區域變數
6. 例外鏈上有 DB 錯誤時，**主訊息**裡的值另行遮罩（#905 B10，見 `_mask_db_values`）：
   asyncpg 編碼參數失敗的 `invalid input for query argument $N: 值` 自 `$N:` 起整段遮；
   其餘引號內容一律遮，只保留 `constraint "…"`、`relation "…"` 等識別名稱與 `'str'` 等型別名

**`logger.exception()` 等帶 `exc_info` 的紀錄**（#833 C2）：由 `install_exception_redaction()`
全域處理，各呼叫點不必改寫，見該函式說明。要把例外訊息寫進 DB 或印到 CLI 時用
`redact_exception_message(exc)`（規則相同）；只看文字的 `redact_sensitive` 不含第 6 項。

**lifespan 啟動 / 關閉失敗**（#905 B11）：Starlette 以 `traceback.format_exc()` 組成**訊息本體**交給
uvicorn，不帶 `exc_info`；由 `redact_lifespan_errors` 包住 lifespan 處理，見該函式說明。

**本模組未涵蓋的既有暴露面**（非本次修正範圍，各自另案追蹤）：
- 訊息本體（`msg % args`）不經遮罩：呼叫端把例外或個資當參數傳進訊息時照樣寫出。
  2026-11-02 盤點全庫只有 `main.py` 讀 `pyproject.toml` 失敗那一處（`OSError`，不含個資）；
  要刻意記 Email 時用 `mask_email`。
- DB 錯誤裡**沒有引號、也不在 `$N:` 之後**的值：PostgreSQL 的主訊息目前都以引號包值，
  asyncpg 編碼器的根因訊息若直接嵌入未加引號的值則不會被遮（2026-11-04 實測常見型別都有引號或不含值）；
  `invalid byte sequence for encoding "UTF8": 0xe4 0xb8` 的位元組尾巴同樣蓋不到。
- PostgreSQL 訊息被翻譯時的引號：`lc_messages` 不是英文時會出現 `»值«`、`「值」` 等，本模組只認 ASCII
  引號。`postgres:17` 映像預設英文；DB 端改語系前要先擴充 `_QUOTE_RE`。
- lifespan 以 `SystemExit` 或含 `KeyboardInterrupt` 的 `BaseExceptionGroup` 失敗時，訊息仍經
  `format_exc()` 原樣交給 uvicorn（`redact_lifespan_errors` 只攔 `Exception`，理由見該函式）。
  `main.py` 的 lifespan 目前沒有 `sys.exit` 與 TaskGroup。
- 非 DB 例外訊息裡的值（如 `int("值")` 的 `ValueError`）：引號規則只套用在 DB 錯誤鏈上，
  因為一般例外的引號內容多是檔案路徑等排查線索，全面遮罩會讓錯誤無從追查。
- `app/core/db.py` 的 `echo=settings.DB_ECHO`：開啟後 SQLAlchemy 引擎自己的 echo log 會
  明文輸出每次查詢的參數值，走獨立的 `sqlalchemy.engine` logger，不經本模組。
  ⚠️ 本項原為 `echo=settings.DEBUG`，#197 AC 5 已**與 `DEBUG` 解耦**（預設關閉、需明示
  `DB_ECHO=true`）——理由是 `DEBUG` 另外閘住三道 production 護欄，共用一個開關會讓
  「為了繞過護欄而開 DEBUG」連帶打開全量 SQL 參數記錄。
- 無固定樣式的個資（如中文姓名）落在訊息本體時無法以規則辨識；本模組的保證
  僅及於上列 1~6 的結構化位置。
"""

import logging
import re
import traceback
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Optional

from sqlalchemy.exc import StatementError

logger = logging.getLogger(__name__)

_MARK = "[敏感內容已遮罩]"

# SQLAlchemy StatementError 訊息的尾段：`[SQL: …]`、`[parameters: …]`、說明連結皆自此開始。
# 整段截掉而非逐段 lookahead——statement 內若含「換行後接 [」會讓逐段比對提前收手、殘留尾段。
_SQL_TAIL_RE = re.compile(r"\n?\[SQL:.*\Z", re.DOTALL)
# asyncpg PostgresError.__str__ 追加的行（見 asyncpg/exceptions/_base.py），
# 其 `Key (欄位)=(值)` 直接含欄位值，且位置在 [SQL: 之前。值本身含換行時 DETAIL 會跨多行、
# 續行沒有前綴，所以從第一個 DETAIL/HINT/CONTEXT 一路刪到 `[SQL:` 或結尾——它們是 asyncpg
# 接在訊息最後的，其後只會是 SQLAlchemy 的 SQL 尾段（#905 security review）。
_PG_DETAIL_RE = re.compile(r"\n(?:DETAIL|HINT|CONTEXT):.*?(?=\n\[SQL:|\Z)", re.DOTALL)
# Pydantic ValidationError 會 echo 觸發驗證失敗的原始輸入值（可能是密碼 / PARAM_VALUE）。
_INPUT_VALUE_RE = re.compile(r"input_value=.*?(?=, input_type=|\]|\Z)", re.DOTALL)
# JWT / API Key 原始值屬禁寫入 log 之敏感資料；保留前綴供比對。
# 各段設長度上限：不設的話每個 `eyJ` 起點都吃到底再回溯，`"eyJ" * 26_000`（約 80 KB）實測 45 秒，
# 而這段跑在 event loop 上——有了 event loop watchdog 就等於可以觸發重啟（#905 B16 security review）
_JWT_RE = re.compile(r"eyJ[\w-]{4,4096}\.[\w-]{4,4096}\.[\w-]{0,4096}")
# 保守樣式：只認一般 Email 字面，避免誤傷檔名 / 網址。長度設上限（RFC 5321：本地端 64、每段網域 63）：
# 不設的話一長串沒有 @ 的字元會讓每個起點都吃到底再回溯，耗時與長度平方成正比——這段跑在
# logger.exception() 當下、與 event loop 同一條執行緒（#905 security review，10 萬字元實測 30 秒以上）
_EMAIL_RE = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")

# `__cause__` / `__context__` 鏈的走訪上限，避免長鏈把 log 撐爆
_MAX_CHAIN = 4
# 判定「鏈上有沒有 DB 錯誤」時的走訪上限：與輸出分開，包了 4 層以上的 DB 錯誤也要認得出來
_MAX_DB_DETECT = 32


def mask_email(email: str) -> str:
    """遮罩 Email 本地端，保留網域供排查（如 wang@example.com → w***@example.com）。

    供**刻意**要把 Email 寫進 log 的呼叫端使用（規範禁記個資完整值，見
    `.claude/rules/sti-backend-logging.md`）。與 `redact_sensitive` 的自動遮罩共用同一規則，
    使「事後掃 log 文字」與「事前遮罩後才寫入」兩條路徑的輸出格式一致、可互相比對。
    """
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _mask_email(match: "re.Match[str]") -> str:
    """`_EMAIL_RE.sub` 用的轉接（規則單一來源見 `mask_email`）。"""
    return mask_email(match.group(0))


def _mask_jwt(match: "re.Match[str]") -> str:
    """只留前 8 碼（規範允許記 KEY_PREFIX / 前 8 碼），其餘截斷。"""
    return f"{match.group(0)[:8]}***"


def redact_sensitive(text: str) -> str:
    """移除 / 遮罩已知會攜帶敏感值的結構化位置；無敏感樣式時原樣回傳。

    移除發生時於結尾附上 `[敏感內容已遮罩]`，讓讀 log 的人知道是「已遮罩」
    而非「本來就沒有」。
    """
    redacted, sql_removed = _SQL_TAIL_RE.subn("", text)
    redacted, detail_removed = _PG_DETAIL_RE.subn("", redacted)
    redacted, _ = _INPUT_VALUE_RE.subn("input_value=[已遮罩]", redacted)
    if sql_removed or detail_removed:
        # 截斷後常留下空行，壓成單行便於 grep；未觸發移除者不改寫排版
        kept = " ".join(line.strip() for line in redacted.splitlines() if line.strip())
        redacted = f"{kept} {_MARK}"
    redacted = _JWT_RE.sub(_mask_jwt, redacted)
    return _EMAIL_RE.sub(_mask_email, redacted)


_VALUE_MARK = "[值已遮罩]"
# asyncpg 編碼參數失敗：`invalid input for query argument $1: <repr 值> (<原因>)`
# （asyncpg/protocol/prepared_stmt.pyx）。非字串值的 repr 沒有引號，所以 `$N:` 之後整段遮；
# 原因另由鏈上的根因（TypeError／ValueError）帶出，經引號規則處理後仍看得到。
# 編碼器自己拋 InterfaceError 時改寫成 `query argument $N: <編碼器訊息>`，沒有 `invalid input for` 前綴。
_ASYNCPG_ARGUMENT_RE = re.compile(
    r"((?:invalid input for )?query argument \$\d+(?: in element #\d+ of executemany\(\) sequence)?): [^\n]*"
)
# 引號前一個字是這些時，引號內是 schema 識別名稱（排查線索、不是個資），保留
_IDENTIFIER_KEYWORDS = frozenset(
    {
        "class",  # SQLAlchemy 前綴 `<class 'asyncpg.exceptions.X'>`
        "column",
        "constraint",
        "database",
        "extension",
        "function",
        "index",
        "relation",
        "role",
        "schema",
        "sequence",
        "table",
        "trigger",
        "type",
        "view",
    }
)
# 根因常見 `'str' object cannot be interpreted as an integer`：單引號內是 Python 型別名，保留
_PYTHON_TYPE_NAMES = frozenset(
    {"str", "int", "float", "bool", "bytes", "NoneType", "list", "tuple", "dict", "set", "Decimal", "UUID"}
    | {"date", "datetime", "time", "timedelta", "datetime.date", "datetime.datetime", "datetime.time"}
)
_QUOTE_RE = re.compile(r"""["']""")
# 引號緊鄰的前一個字（`constraint "X"` 的 constraint）。只對引號前一小段回看：若把 `(\w+) ` 併進
# 找引號的 regex，連續無空白的長值會讓每個起點都貪婪吃完再回溯，耗時與長度平方成正比（code review）
_KEYWORD_BEFORE_RE = re.compile(r"(\w+) \Z")
_KEYWORD_LOOKBACK = 32


def _is_db_exception(exc: BaseException) -> bool:
    """SQLAlchemy 的 StatementError 系列（含 DBAPIError）、asyncpg 例外與 SQLAlchemy 方言層的轉接例外。

    `StatementError` 本體是 bind processor 失敗時拋的，主訊息形如 `(builtins.ValueError) … '值'`。
    """
    module = type(exc).__module__
    return (
        isinstance(exc, StatementError)
        or module == "asyncpg"
        or module.startswith(("asyncpg.", "sqlalchemy.dialects."))
    )


def _keeps_quoted(text: str, start: int, quote: str, body: str) -> bool:
    keyword = _KEYWORD_BEFORE_RE.search(text[max(0, start - _KEYWORD_LOOKBACK) : start])
    if keyword is not None and keyword.group(1).lower() in _IDENTIFIER_KEYWORDS:
        return True
    return quote == "'" and body in _PYTHON_TYPE_NAMES


def _mask_quoted_values(text: str) -> str:
    """識別名稱與型別名保留，其餘引號內容遮掉。

    PG 不跳脫值裡的引號（`"ab"cd"`），所以值的遮罩一路延伸到**全文最後一個**同種引號；值也可能含換行，
    所以不逐行處理。引號沒閉合（訊息被截斷）時遮到結尾。寧可多遮一個識別名稱，也不漏出半個值。
    """
    parts: list[str] = []
    pos = 0
    while (match := _QUOTE_RE.search(text, pos)) is not None:
        quote = match.group(0)
        start = match.start()
        close = text.find(quote, start + 1)
        if close == -1:
            parts.append(text[pos:start] + _VALUE_MARK)
            return "".join(parts)
        if _keeps_quoted(text, start, quote, text[start + 1 : close]):
            parts.append(text[pos : close + 1])
            pos = close + 1
            continue
        parts.append(text[pos:start] + _VALUE_MARK)
        pos = text.rfind(quote) + 1
    parts.append(text[pos:])
    return "".join(parts)


def _mask_db_values(text: str) -> str:
    """DB 錯誤主訊息裡的值（#905 B10）：PG 把無法解析的輸入放在主訊息，不在 DETAIL。

    採「引號內一律遮、識別名稱例外」而非逐條列句型：PG 會帶值的句型很多
    （`invalid input syntax for type …: "值"`、`value "值" is out of range …`、`malformed array literal: "值"`…），
    列舉式漏一條就外洩；預設遮掉的代價只是偶爾多遮一個識別名稱（2026-11-04 使用者裁示）。

    只處理 `[SQL:` 之前：其後的 SQL 本文與參數之後由 `redact_sensitive` 整段截掉，SQL 裡的引號
    若一起參與「遮到最後一個引號」，會把主訊息後面的識別名稱也卷進去。
    """
    tail = _SQL_TAIL_RE.search(text)
    head, rest = (text[: tail.start()], text[tail.start() :]) if tail else (text, "")
    head = _ASYNCPG_ARGUMENT_RE.sub(rf"\1: {_VALUE_MARK}", head)
    return _mask_quoted_values(head) + rest


#: 例外訊息遮罩前的長度上限：所有規則的耗時因此有上界，單一例外也撐不爆 log（#905 B16 security review）。
#: 截斷點切在值的引號中間時，DB 規則對未閉合的引號遮到結尾，不會漏出半個值
_MAX_MESSAGE_CHARS = 8192
_TRUNCATED_MARK = "…[訊息過長，已截斷]"


def _redact_message(exc: BaseException, *, db_rules: bool) -> str:
    text = str(exc)
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[:_MAX_MESSAGE_CHARS] + _TRUNCATED_MARK
    return redact_sensitive(_mask_db_values(text) if db_rules else text)


def redact_exception_message(exc: BaseException) -> str:
    """例外訊息去識別化後的文字，給要把訊息寫進 DB 或印到 CLI 的呼叫端用（規則與 log 相同）。

    例外鏈上有 DB 錯誤時另套用 DB 值遮罩；只看文字的 `redact_sensitive` 分不出這一點。
    """
    return _redact_message(exc, db_rules=_has_db_exception(exc))


def _has_db_exception(exc: BaseException) -> bool:
    """鏈上有沒有 DB 錯誤：`__cause__` 與 `__context__` 都走、含 ExceptionGroup 子例外。

    與 `_exception_chain` 分開：那邊只跟一條、最多 4 層，是為了輸出長度；這裡漏判就是漏遮。
    """
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending and len(seen) < _MAX_DB_DETECT:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if _is_db_exception(current):
            return True
        group = getattr(current, "exceptions", None)
        if isinstance(group, (list, tuple)):
            pending.extend(group)
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return False


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """依 `__cause__`（優先）/ `__context__` 走訪例外鏈，含 ExceptionGroup 子例外。

    包裝型例外（`raise AppFailure(...) from IntegrityError(...)`）的根因在鏈上，
    只記最外層會失去真正的失敗原因（如違反的約束名）。
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending and len(chain) < _MAX_CHAIN:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        group = getattr(current, "exceptions", None)
        if isinstance(group, (list, tuple)):  # ExceptionGroup / anyio TaskGroup
            pending.extend(group)
        nested: Optional[BaseException] = current.__cause__ or current.__context__
        if nested is not None:
            pending.append(nested)
    return chain


def format_exception_for_log(exc: BaseException) -> str:
    """將例外（含鏈上根因）格式化為「可排查但去識別化」的字串。

    每層組成：完整型別名稱 + 遮罩後訊息（壓成單行便於 grep）+ 堆疊框架。
    刻意不用 `traceback.format_exc()` / `format_exception()`——兩者會帶出未遮罩的
    例外訊息與整條 `__cause__` 鏈訊息。
    """
    blocks: list[str] = []
    chain = _exception_chain(exc)
    # 鏈上任一層是 DB 錯誤就整條套用：根因（asyncpg 的編碼錯誤）與包裝者都可能轉述那個值
    db_rules = _has_db_exception(exc)
    for index, current in enumerate(chain):
        prefix = "" if index == 0 else "起因於 "
        exc_type = f"{type(current).__module__}.{type(current).__qualname__}"
        message = " ".join(_redact_message(current, db_rules=db_rules).split())
        header = f"{prefix}{exc_type}: {message}"
        frames = "".join(traceback.format_tb(current.__traceback__)).rstrip()
        blocks.append(f"{header}\n{frames}" if frames else header)
    return "\n".join(blocks)


def install_exception_redaction() -> None:
    """全域安裝：帶 `exc_info` 的 log 紀錄一律以 `format_exception_for_log` 輸出例外（#833 C2）。

    ## 為什麼掛在 LogRecordFactory，而不是 root 的 Filter／Formatter

    正式環境 root logger **沒有 handler**——uvicorn 只替自己的 logger 設 handler，應用程式的紀錄一路
    傳到 root 之後由 `logging.lastResort` 輸出到 stderr。掛在 root 的 handler 上等於沒掛；另加 handler
    又會讓原本被 lastResort 濾掉的 INFO 突然出現，改變 log 量。Logger 層的 Filter 則只對「直接記在該
    logger 上」的紀錄生效，子 logger 傳上來的不經過它。

    Factory 在紀錄**產生時**就預先填好 `exc_text`：標準 `Formatter.format` 只在 `exc_text` 為空時才自己
    呼叫 `formatException`，所以不論最後由哪個 handler、哪個 logger（含 apscheduler、uvicorn）輸出，
    印出來的都是去識別化的版本。

    ⚠️ 刻意**保留 `exc_info`**：caplog 與讀 `record.exc_info` 的既有程式照常運作。

    ## 會繞過本層的寫法（目前全庫皆無，引入時要處理）

    - 自訂 Formatter 直接讀 `exc_info`（而非 `exc_text`）
    - 之後安裝的套件以 `setLogRecordFactory` **覆蓋**而非包住本 factory（Sentry、structlog 等整合要確認）
    - `logging.makeLogRecord(dict)`（QueueHandler / socket 轉送）：先建紀錄再補欄位，factory 看不到 `exc_info`
    - 子行程：factory 是行程內狀態，新行程沒 import `main` 就沒裝，要自行呼叫本函式

    ## 格式化失敗不可往外拋

    factory 跑在呼叫 `logger.exception()` 的那一行（通常在 `except` 區塊裡）。原本格式化出錯發生在
    handler、由 `Handler.handleError` 吞掉；搬到這裡若不攔，例外的 `__str__` 本身會拋時，**記 log 就讓
    呼叫端中斷**——發信 worker 的迴圈因此結束（code / security review）。失敗時只留型別，⛔ 不可退回
    `Formatter.formatException`：那會把未遮罩的內容寫出去。

    重複呼叫不會包兩層。
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "redacts_exceptions", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        if record.exc_info and record.exc_info[1] is not None and not record.exc_text:
            exc = record.exc_info[1]
            try:
                record.exc_text = format_exception_for_log(exc)
            except Exception:
                record.exc_text = f"{type(exc).__module__}.{type(exc).__qualname__}: [例外訊息格式化失敗，已省略]"
        return record

    factory.redacts_exceptions = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


# 正式環境由 logging.lastResort 輸出、只印訊息不印 logger 名，所以指向可 grep 的訊息文字
_LIFESPAN_FAILED = "lifespan 啟動或關閉失敗，原因見前一筆「lifespan 執行失敗」的 ERROR log"


def redact_lifespan_errors(
    lifespan: Callable[[Any], AbstractAsyncContextManager[Any]],
) -> Callable[[Any], AbstractAsyncContextManager[Any]]:
    """包住 FastAPI lifespan：啟動／關閉失敗時，交給 uvicorn 的文字不含原例外訊息（#905 B11）。

    Starlette 在 lifespan 拋錯時以 `traceback.format_exc()` 組成 `lifespan.*.failed` 的 message，
    uvicorn 再把它當**訊息本體**記錄、不帶 `exc_info`——`install_exception_redaction` 管不到，
    原例外訊息（含 DB 錯誤的綁定參數）與整條例外鏈會原樣寫出。

    作法：原例外先以帶 `exc_info` 的 log 記下（走既有遮罩），再改拋一個只有固定文字、
    `from None` 切斷例外鏈的 RuntimeError；`format_exc()` 因此只剩檔名、行號與原始碼行。
    失敗仍往外拋，uvicorn 照樣以非零結束。

    ⚠️ 只攔 `Exception`：`CancelledError`／`KeyboardInterrupt` 是關閉流程本身，不能換掉；
    `SystemExit` 與 `BaseExceptionGroup` 同理，目前 lifespan 也沒有會拋它們的寫法（見檔頭「未涵蓋」）。
    """

    @asynccontextmanager
    async def wrapped(app: Any) -> AsyncIterator[Any]:
        try:
            async with lifespan(app) as state:
                yield state
        except Exception as exc:
            logger.error("lifespan 執行失敗", exc_info=exc)
            raise RuntimeError(_LIFESPAN_FAILED) from None

    return wrapped
