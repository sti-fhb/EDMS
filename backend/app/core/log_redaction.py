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

**`logger.exception()` 等帶 `exc_info` 的紀錄**（#833 C2）：由 `install_exception_redaction()`
全域處理，各呼叫點不必改寫，見該函式說明。

**本模組未涵蓋的既有暴露面**（非本次修正範圍，各自另案追蹤）：
- 訊息本體（`msg % args`）不經遮罩：呼叫端把例外或個資當參數傳進訊息時照樣寫出。
  2026-11-02 盤點全庫只有 `main.py` 讀 `pyproject.toml` 失敗那一處（`OSError`，不含個資）；
  要刻意記 Email 時用 `mask_email`。
- Starlette 的 lifespan 啟動 / 關閉失敗以 `traceback.format_exc()` 組成**訊息本體**交給 uvicorn 記錄，
  不帶 `exc_info`，`install_exception_redaction` 管不到。
- 值出現在**主訊息**裡的 DB 錯誤：asyncpg 編碼參數失敗的 `invalid input for query argument $N: '值'`、
  PostgreSQL 的 `invalid input syntax for type …: "值"` 等。它們在 `[SQL:` 之前、也不是 `DETAIL` 行，
  只有 Email／JWT 樣式會被遮罩，姓名、身分證號會留下（#833 security review M3，待另案擴充規則）。
- `app/core/db.py` 的 `echo=settings.DEBUG`：dev 環境下 SQLAlchemy 引擎自己的
  echo log 會明文輸出每次查詢的參數值，走獨立的 `sqlalchemy.engine` logger，
  不經本模組。
- 無固定樣式的個資（如中文姓名）落在訊息本體時無法以規則辨識；本模組的保證
  僅及於上列 1~4 的結構化位置。
"""

import logging
import re
import traceback
from typing import Any, Optional

_MARK = "[敏感內容已遮罩]"

# SQLAlchemy StatementError 訊息的尾段：`[SQL: …]`、`[parameters: …]`、說明連結皆自此開始。
# 整段截掉而非逐段 lookahead——statement 內若含「換行後接 [」會讓逐段比對提前收手、殘留尾段。
_SQL_TAIL_RE = re.compile(r"\n?\[SQL:.*\Z", re.DOTALL)
# asyncpg PostgresError.__str__ 追加的行（見 asyncpg/exceptions/_base.py），
# 其 `Key (欄位)=(值)` 直接含欄位值，且位置在 [SQL: 之前。
_PG_DETAIL_RE = re.compile(r"\n(?:DETAIL|HINT|CONTEXT):[^\n]*")
# Pydantic ValidationError 會 echo 觸發驗證失敗的原始輸入值（可能是密碼 / PARAM_VALUE）。
_INPUT_VALUE_RE = re.compile(r"input_value=.*?(?=, input_type=|\]|\Z)", re.DOTALL)
# JWT / API Key 原始值屬禁寫入 log 之敏感資料；保留前綴供比對。
_JWT_RE = re.compile(r"eyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*")
# 保守樣式：只認一般 Email 字面，避免誤傷檔名 / 網址
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# `__cause__` / `__context__` 鏈的走訪上限，避免長鏈把 log 撐爆
_MAX_CHAIN = 4


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
    for index, current in enumerate(_exception_chain(exc)):
        prefix = "" if index == 0 else "起因於 "
        exc_type = f"{type(current).__module__}.{type(current).__qualname__}"
        message = " ".join(redact_sensitive(str(current)).split())
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
