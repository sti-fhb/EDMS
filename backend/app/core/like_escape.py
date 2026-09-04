"""LIKE / ILIKE 模式跳脫共用工具（防使用者輸入之 `%` / `_` 改變比對範圍）。

使用者輸入的關鍵字若含 LIKE 萬用字元（`%` 任意字串、`_` 任意單字元），未跳脫時會被當萬用字元、
擴大或扭曲比對範圍（非 SQL Injection——值仍由 SQLAlchemy 綁定，但語意失真、亦可造成過度比對負擔）。
本工具將 `%` / `_` / `\\` 跳脫為字面，配合 `.ilike(pattern, escape=LIKE_ESCAPE_CHAR)` 使用。

用法：
    stmt.where(col.ilike(contains(keyword), escape=LIKE_ESCAPE_CHAR))
"""

# `\\` 須先跳脫（避免二次跳脫錯亂）；PostgreSQL LIKE 之 ESCAPE 預設即 `\\`，此處明確指定。
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})

LIKE_ESCAPE_CHAR = "\\"


def escape_like(term: str) -> str:
    """把 term 中的 LIKE 萬用字元（`%` / `_` / `\\`）跳脫為字面。"""
    return term.translate(_LIKE_ESCAPE)


def contains(term: str) -> str:
    """回傳「包含」比對模式 `%{escaped}%`（term 中萬用字元視為字面）。

    須搭配 `.ilike(contains(term), escape=LIKE_ESCAPE_CHAR)`。
    """
    return f"%{escape_like(term)}%"
