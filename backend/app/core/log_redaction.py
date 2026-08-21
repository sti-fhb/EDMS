"""log 去識別化工具（#123）。

SQLAlchemy 的 `StatementError` 系列（`IntegrityError` / `DataError` /
`OperationalError` …）在 `__str__` 時會把 SQL 與**綁定參數**一併附上。因此帶個資的
DB 操作若拋出未攔截例外，該筆個資（Email / 姓名等）會原樣寫進 log——log 的流向通常
比 DB 寬鬆（複製到開發機、送入收集服務、貼上通訊軟體），個資因此離開受控環境。
違反 `.claude/rules/sti-backend-logging.md` §禁寫入 log 的敏感資料。

設計取捨：**不以「不記 traceback」換取安全**（線上問題會無法追查），而是移除已知
會攜帶參數值的區段、遮罩 Email，並改以「例外型別 + 堆疊框架」表達位置——
`traceback.format_tb` 只輸出檔案 / 行號 / 原始碼行，不含例外訊息、不含區域變數。

已知界線：驅動層自行把值寫進訊息本體（如 psycopg2 的 `DETAIL: Key (email)=(…)`）時，
Email 由本模組的遮罩規則覆蓋；但**中文姓名一類無固定樣式的個資無法以規則辨識**，
故本模組的保證僅及於「移除參數區段 + 遮罩 Email」。本專案使用 asyncpg，其例外訊息
不含 DETAIL 行，主要暴露面即參數區段。
"""

import re
import traceback

# SQLAlchemy 訊息中會攜帶 SQL 或參數值的區段；各區段延伸至下一個區段、
# 說明連結行（(Background on this error at: …)）或字串結尾為止。
_SENSITIVE_SECTION_RE = re.compile(
    r"\[(?:SQL|parameters|cached since [^\]:]*):.*?(?=\n\[|\n\(Background|\Z)",
    re.DOTALL,
)
_SECTION_MARK = "[SQL 與參數已遮罩]"
_BLANK_LINES_RE = re.compile(r"[ \t]*\n[ \t]*(?:\n[ \t]*)+")
# 保守樣式：只認一般 Email 字面，避免誤傷檔名 / 網址
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _mask_email(match: "re.Match[str]") -> str:
    """遮罩 Email 本地端，保留網域供排查（如 wang@example.com → w***@example.com）。"""
    local, _, domain = match.group(0).partition("@")
    return f"{local[:1]}***@{domain}"


def redact_sensitive(text: str) -> str:
    """移除會攜帶參數值的區段並遮罩 Email；無敏感樣式時原樣回傳。

    移除發生時於結尾附上 `[SQL 與參數已遮罩]`，讓讀 log 的人知道是「已遮罩」
    而非「本來就沒有」。
    """
    redacted, removed = _SENSITIVE_SECTION_RE.subn("", text)
    if removed:
        redacted = f"{_BLANK_LINES_RE.sub(chr(10), redacted).rstrip()} {_SECTION_MARK}"
    return _EMAIL_RE.sub(_mask_email, redacted)


def format_exception_for_log(exc: BaseException) -> str:
    """將例外格式化為「可排查但去識別化」的單一字串。

    組成：完整型別名稱 + 遮罩後訊息（壓成單行便於 grep）+ 堆疊框架。
    刻意不用 `traceback.format_exc()` / `format_exception()`——兩者會再次帶出
    未遮罩的例外訊息與 `__cause__` 鏈訊息。
    """
    exc_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    message = " ".join(redact_sensitive(str(exc)).split())
    frames = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
    return f"{exc_type}: {message}\n{frames}" if frames else f"{exc_type}: {message}"
