"""遮罩 access log 中的憑證型 query 參數（#255）。

## 為什麼需要

ET 影片取檔以**播放票**認證（`et/learning/video_ticket`）——`<video src>` 送不出
`Authorization` header，票只能放進 query string。而：

1. uvicorn 的 `access_log` 預設開啟（`uvicorn/config.py`）
2. 其 request line 由 `get_path_with_query_string()` 組成，**query string 原樣附上**
3. `<video>` 對同一個 URL 會反覆發出 Range 請求 → 同一張票被寫進 log **數十次**

`core/log_redaction._JWT_RE` 雖然會遮罩 JWT，但它只服務 `format_exception_for_log()`，
**完全不經過 `uvicorn.access` logger**。

`.claude/rules/sti-backend-logging.md` 的「禁寫入 log 之敏感資料」第 2 條即為
「JWT / API Key 原始值」——本模組補上那道控制。

## 涵蓋範圍與限制

只處理**本行程**的 `uvicorn.access` logger。反向代理（nginx 等）自己的 access log
不在此範圍——部署時 `log_format` 應使用 `$uri` 而非 `$request`，見
`docs/ref/deployment-client-ip.md`。
"""

import logging
import re
from typing import Final

#: 需遮罩的 query 參數名。目前只有影片播放票；新增憑證型參數時一併加入。
_SENSITIVE_QUERY_KEYS: Final = ("t",)

_REDACTED: Final = "[redacted]"

#: `?t=xxx` / `&t=xxx` → 值換成 `[redacted]`。
#:
#: 以參數名為錨點而非比對「看起來像 JWT 的字串」：後者會漏掉未來換成別種格式的票，
#: 而遮罩漏掉的代價是憑證明文留在 log 裡。
_PATTERNS: Final = tuple(re.compile(rf"([?&]{re.escape(key)}=)[^&\s]+") for key in _SENSITIVE_QUERY_KEYS)


def redact_query_credentials(text: str) -> str:
    """把 query string 中的憑證值換成 `[redacted]`。"""
    for pattern in _PATTERNS:
        text = pattern.sub(rf"\1{_REDACTED}", text)
    return text


class QueryCredentialRedactionFilter(logging.Filter):
    """掛在 `uvicorn.access` 上，遮罩 request line 中的憑證。

    uvicorn 的 access record 以 `args` 傳遞欄位（`%s - "%s %s HTTP/%s" %d`），
    request line 在 `args[2]`。**就地改寫 `args` 而非 `msg`**——`msg` 是格式字串，
    改它無效。

    `filter()` 一律回 `True`：本 filter 的作用是改寫，不是過濾掉紀錄。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact_query_credentials(a) if isinstance(a, str) else a for a in args)
        elif isinstance(args, str):
            record.args = redact_query_credentials(args)
        return True


def install_access_log_redaction() -> None:
    """於應用啟動時掛上遮罩 filter（idempotent）。"""
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, QueryCredentialRedactionFilter) for f in logger.filters):
        return
    logger.addFilter(QueryCredentialRedactionFilter())
