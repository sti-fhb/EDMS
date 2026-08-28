"""CSV 匯出共用工具。

`csv.writer` 只處理逗號 / 換行 / 引號跳脫，**不防公式注入**（CWE-1236）：試算表（Excel / Calc）
開檔時會把以 `=` `+` `-` `@` Tab CR 開頭的欄位當公式執行。匯出含使用者自由輸入欄位（文件名 /
廢止原因等）時，一律經 `sanitize_csv_cell` 前置單引號中和。

> 既有 `dp/audit/query_service.py` 亦有同款私有實作；本檔為 canonical 共用位置，後續匯出應改用此處
> （dp-audit 之遷移屬既有碼重構、另行處理）。
"""

# 可觸發試算表公式注入的前導字元（含 tab / CR）。
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(text: str) -> str:
    """CSV formula injection 防護：以危險字元開頭者前置單引號，令試算表視為文字。"""
    if text and text[0] in _CSV_INJECTION_PREFIXES:
        return "'" + text
    return text
