"""log 控制字元轉義：使用者可控值不得在 log 裡偽造整行或操控終端機（#913）。

## 為何存在

使用者可控的值經由訊息參數或例外訊息進到 log 時，控制字元會原樣寫出：

- **ESC（`\\x1b`）**：以 `tail` / `cat` 看 log 時 ANSI escape 序列會被終端機執行——畫面變色、
  清空、游標回捲蓋掉前面的內容，讓 log 看起來和實際內容不同
- **換行、`U+2028` 等分行字元**：一筆 log 被拆成多行，可以偽造一行看起來像系統紀錄的文字
- **格式字元（Unicode 類別 Cf）**：雙向覆寫可視覺重排一行；零寬字元可規避事後 `grep`

觸發案例：DP06 的 Cron 填 `0 8 * * \\x1b[31mX`，APScheduler 的例外訊息原樣帶出 ESC（#902）。
改動前只有零星的逐點處理（`dp/notify/service._safe_log`），其餘 `logger.*` 皆未過濾。

## 與 `log_redaction` 的分工與先後

| | `log_redaction` | 本模組 |
|---|---|---|
| 護的性質 | 機密性——SQL 參數、`DETAIL:` 行、Email、JWT 不得出現在 log | 完整性——一筆 log 不得被拆行、不得操控終端機 |
| 手法 | 截掉 / 遮罩 | 把控制字元**轉義**成可見字面（`ESC` → `\\x1b`、換行 → `\\n`），不刪內容 |

⚠️ **遮罩必須先於轉義**：`log_redaction` 以換行定位 `DETAIL:` 行、以 `\\n?[SQL:` 截尾，先轉義的話
換行變成字面 `\\n`，比對失配、個資原樣外洩。故 `install_control_char_escape()` 一律**包在**遮罩
factory 外層（先呼叫內層、再轉義），且自行先安裝遮罩，不依賴呼叫端的安裝順序。

## 掛載方式：沿用 LogRecordFactory，不掛 handler filter

理由同 `log_redaction.install_exception_redaction`：正式環境 root logger 沒有 handler，紀錄由
`logging.lastResort` 輸出，掛 handler 等於沒掛。Factory 在紀錄**產生時**就地改寫，任何 logger
（含 apscheduler、uvicorn）、任何 handler 輸出的都是轉義後的版本。

**逐項轉義、不攤平訊息**：`msg` 與每個字串參數各自轉義，`args` 維持原結構。`uvicorn.access`
的憑證遮罩（`access_log_redaction`）是之後才跑的 logger filter，靠 `args` 定位 request line——
攤平成單一字串會讓它失效。轉義不影響該遮罩命中：參數名錨點不含控制字元，而值被轉義後只會更長、
`[^&\\s]+` 照樣整段吃掉。

## 字元判準：類別式，不逐一列舉壞字元

轉義 C0 控制字元（tab 除外）、DEL、C1 控制字元（含 `U+0085` NEL）、`U+2028` / `U+2029`、
**整個 Cf 類別**與孤立代理字元（後者會讓整筆紀錄在 emit 時被 `UnicodeEncodeError` 靜默丟棄）。
tab 與一切可列印字元放行——中文、全形空白（Zs，不是 Cf）不受影響。
Cf 的碼位範圍寫成常數而非 import 時計算（掃全碼位約 0.7 秒，每個行程啟動都要付）；與
`unicodedata` 是否一致由 `tests/unit/test_core_log_sanitize.py` 逐碼位核對，Python 升級帶進
新的 Cf 字元時會轉紅。

## 例外 traceback 保留換行，但續行縮排

`exc_text` / `stack_info` 本質多行，吃掉換行等於吃掉診斷價值，故只轉義換行以外的控制字元。
只保留換行並不夠——續行若從第 0 欄起頭，與真正的 log 行無從分辨——故續行一律補兩格縮排。
第一行是 `format_exception_for_log` 的「完整型別名: 訊息」，訊息已壓成單行，開頭不受使用者控制。

## 已知邊界

- **訊息本體刻意多行者會被壓成一行**：uvicorn 記錄 Starlette lifespan 啟動 / 關閉失敗時，把
  `traceback.format_exc()` 當訊息本體、不帶 `exc_info`（`uvicorn/lifespan/on.py`），轉義後變成一行
  帶字面 `\\n` 的長字串。內容完整、只是難讀；訊息本體無從分辨「刻意多行」與「被注入的換行」，
  故不為它開例外。自家程式要附堆疊一律用 `exc_info`（見 `sti-backend-logging.md`）
- `%r` 與容器參數會雙重轉義：`repr()` 本就會轉義控制字元，先轉義過的字串再經 `repr` 會顯示成
  `'x\\\\ny'`。方向安全，只是多一層反斜線
- 數值參數不檢查：`logger.info("%c", 27)` 會輸出原始 ESC。全庫沒有以 `%c` 記使用者輸入的寫法
- 非字串、非數值的參數在紀錄產生時多算一次 `str()` / `repr()`（格式化時還會再算）。一般 log 的
  參數是字串與數字，不受影響；大型容器、ORM 物件的成本約加倍，`__repr__` 若有副作用也會多觸發一次
- 參數的 `__str__` / `__repr__` 自身拋例外時原樣保留（之後格式化照樣失敗、走 `handleError`）
- `handleError()` 直寫 stderr 的例外鏈與 `sys.excepthook` 的未捕捉例外不經紀錄，本模組攔不到
- 逐點處理（`_safe_log`）**不因本模組而拆除**：它另有截斷至 200 字元的防灌量作用，本模組不截斷
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

from app.core.log_redaction import install_exception_redaction

# Unicode 類別 Cf（格式字元），Unicode 15.0.0 / Python 3.12。由 unicodedata 逐碼位產生；
# 與執行環境的 unicodedata 是否一致由測試核對（見模組說明）。
_FORMAT_CHARS = (
    r"­؀-؅\u061C۝܏࢐-࢑࣢᠎​-\u200F\u202A-\u202E"
    r"⁠-⁤\u2066-⁯﻿￹-￻\U000110bd\U000110cd\U00013430-\U0001343f"
    r"\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f"
)
_SURROGATES = r"\ud800-\udfff"

#: 單行欄位（訊息與參數）：含換行一律轉義；tab（\x09）放行
_LINE_UNSAFE = re.compile(rf"[\x00-\x08\x0a-\x1f\x7f-\x9f  {_FORMAT_CHARS}{_SURROGATES}]")
#: 多行欄位（traceback）：放行換行，其餘同上
_BLOCK_UNSAFE = re.compile(rf"[\x00-\x08\x0b-\x1f\x7f-\x9f  {_FORMAT_CHARS}{_SURROGATES}]")

_CONTINUATION_INDENT = "  "

#: 轉義本身失敗時的替代訊息：不含任何原始內容
_FAILURE_PLACEHOLDER = "[log 控制字元轉義失敗，內容已略去]"


def _escape(match: "re.Match[str]") -> str:
    """單一控制字元轉為 Python 字面表示（`\\n`、`\\x1b`、`\\u2028`…）。"""
    return match.group().encode("unicode_escape").decode("ascii")


def sanitize_log_line(text: str) -> str:
    """轉義單行欄位的控制字元（含換行）。未命中時回傳原物件。"""
    return _LINE_UNSAFE.sub(_escape, text)


def sanitize_log_block(text: str) -> str:
    """轉義多行欄位的控制字元，保留換行、續行補縮排。"""
    escaped = _BLOCK_UNSAFE.sub(_escape, text)
    if "\n" not in escaped:
        return escaped
    return escaped.replace("\n", "\n" + _CONTINUATION_INDENT)


class _Escaped:
    """取代 `str()` / `repr()` 含控制字元的非字串參數；`%s` 與 `%r` 各自輸出轉義後的版本。"""

    __slots__ = ("_str", "_repr")

    def __init__(self, str_text: str, repr_text: str) -> None:
        self._str = str_text
        self._repr = repr_text

    def __str__(self) -> str:
        return self._str

    def __repr__(self) -> str:
        return self._repr


def _sanitize_arg(value: Any) -> Any:
    """轉義單一參數；無須轉義時回傳原物件（`%d` 等格式照常運作）。

    只有精確的 `str` 直接轉義：`re.sub` 對 str 子類別一律回傳新的純 `str`，`(str, Enum)` 這類覆寫
    `__str__` 的子類別會因此由 `E.A` 變成 `a`，故子類別走下方 `str()` / `repr()` 的路徑。
    """
    if type(value) is str:
        return sanitize_log_line(value)
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        as_str, as_repr = str(value), repr(value)
    except Exception:
        return value
    clean_str, clean_repr = sanitize_log_line(as_str), sanitize_log_line(as_repr)
    if clean_str is as_str and clean_repr is as_repr:
        return value
    return _Escaped(clean_str, clean_repr)


def _sanitize_args(args: Any) -> Any:
    """`LogRecord.args` 只會是 tuple 或單一 Mapping；維持原結構，無變動時回傳原物件。"""
    if isinstance(args, tuple):
        cleaned = tuple(_sanitize_arg(a) for a in args)
        return args if all(new is old for new, old in zip(cleaned, args, strict=True)) else cleaned
    if isinstance(args, Mapping):
        cleaned_map = {k: _sanitize_arg(v) for k, v in args.items()}
        return args if all(cleaned_map[k] is v for k, v in args.items()) else cleaned_map
    return args


def sanitize_record(record: logging.LogRecord) -> None:
    """就地轉義紀錄的 `msg`、`args`、`exc_text`、`stack_info`。

    ⚠️ 失敗時**不得外拋**：factory 跑在呼叫 `logger.*` 的那一行，拋出去會讓呼叫端的 `except`
    區塊改道、排程 job 中斷。寧可丟掉本筆內容（替代訊息不含原文，也就不會帶出未轉義的字元）。
    """
    try:
        record.msg = _sanitize_arg(record.msg)
        record.args = _sanitize_args(record.args)
        if record.exc_text:
            record.exc_text = sanitize_log_block(record.exc_text)
        if record.stack_info:
            record.stack_info = sanitize_log_block(record.stack_info)
    except Exception:
        record.msg = _FAILURE_PLACEHOLDER
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None


def install_control_char_escape() -> None:
    """全域安裝：每筆 log 紀錄產生時轉義控制字元（#913）。

    先安裝 `install_exception_redaction`（冪等），再把本層包在外面——遮罩先於轉義，不依賴
    呼叫端的安裝順序。本層同時標上 `redacts_exceptions`：之後再呼叫
    `install_exception_redaction()` 會視為已安裝而略過，不會把遮罩包到轉義外面。

    重複呼叫不會包兩層。
    """
    install_exception_redaction()
    current = logging.getLogRecordFactory()
    if getattr(current, "escapes_control_chars", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        sanitize_record(record)
        return record

    factory.escapes_control_chars = True  # type: ignore[attr-defined]
    factory.redacts_exceptions = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
