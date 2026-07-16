"""pytest-xdist 並行測試的 per-worker DB 命名工具。

並行跑 integration 測試時，每個 xdist worker 需要自己的資料庫，否則多行程會
互相 DROP SCHEMA 踩到對方。這裡只負責「算出 worker 專屬的庫名」這段純字串邏輯，
真正的建庫 / 接線在 tests/integration/conftest.py。

設計刻意保持為純函式（不連 DB），方便一眼看懂；正確性由「跑全套 `pytest -n auto`」
持續驗證，不另寫測試（屬測試基礎建設，非業務功能）。
"""

from urllib.parse import urlparse, urlunparse

# PostgreSQL 識別字上限 63 字元
_PG_IDENTIFIER_MAX = 63


def worker_database_url(base_url: str, worker: str | None) -> str:
    """在 base_url 的庫名後加上 worker 後綴，回傳新的連線 URL。

    Args:
        base_url: 基底連線字串（worktree 模式下已是分支專屬庫，如 .../test_edms_feature_x）。
        worker: xdist worker 代號（如 "gw0"）；None 或空字串代表非並行，原樣回傳。

    Returns:
        worker 專屬的連線 URL；庫名超過 63 字元時截斷，確保不超出 PostgreSQL 限制。
    """
    if not worker:
        return base_url

    parsed = urlparse(base_url)
    dbname = parsed.path.lstrip("/")
    # 後綴最多 63 字，超出時截掉庫名前段（保留完整 _worker 後綴以維持唯一性）
    suffix = f"_{worker}"
    keep = _PG_IDENTIFIER_MAX - len(suffix)
    worker_db = f"{dbname[:keep]}{suffix}"
    return urlunparse(parsed._replace(path=f"/{worker_db}"))
