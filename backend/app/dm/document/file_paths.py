"""檔案落盤路徑之 storage-root 圍籬（#160）。

讀 / 寫端共用同一根目錄常數（`settings.DM_FILE_STORAGE_ROOT`）與圍籬邏輯，避免上傳端與串流端 drift。
獨立為 leaf 模組（僅依賴 `os` / `logging` / `settings` / `AppError`），不引入 `app.services`，避免與
`file_store`（→ `app.services` → DM integration Service）形成循環 import。
"""

import logging
import os

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def storage_root() -> str:
    """檔案儲存根目錄之正規化絕對路徑（單一事實來源：settings.DM_FILE_STORAGE_ROOT）。"""
    return os.path.realpath(settings.DM_FILE_STORAGE_ROOT)


def _resolved_within_root(path: str) -> str | None:
    """path 正規化（解析 `..` / symlink）後若落在 storage root 內回其 canonical 絕對路徑，否則 None。

    fail-closed：None / 空字串 / 非字串、跨磁碟（Windows commonpath ValueError）、逃出根目錄一律回 None。
    單次 realpath——回傳值即「被驗證且將被串流」的同一路徑（避免 validate 與 serve 取不同解析）。
    """
    if not isinstance(path, str) or not path:
        return None
    root = storage_root()
    try:
        resolved = os.path.realpath(path)
        return resolved if os.path.commonpath([root, resolved]) == root else None
    except (ValueError, TypeError):
        return None


def is_within_root(path: str) -> bool:
    """path 正規化後是否落在 storage root 內（fail-closed，見 `_resolved_within_root`）。"""
    return _resolved_within_root(path) is not None


def resolve_within_root(file_path: str, *, not_found: AppError) -> str:
    """讀取端 storage-root 圍籬：回正規化後之安全路徑；逃逸出根目錄 → raise 呼叫端提供之 `not_found`。

    防禦深度——即使 `DM_DOC_VERSION.FILE_PATH` 因落盤層瑕疵含 `../` / 絕對路徑逃逸，串流端亦不外洩
    根目錄外檔案（讀取者可能為最低權限閱覽者 / 無 DM 角色之 ET 學員）。錯誤文案由各模組 `not_found`
    自帶（避免與該端點其他 404 措辭不一致）。逃逸時記安全事件（**不記落盤路徑**，遵 sti-backend-logging）。
    """
    resolved = _resolved_within_root(file_path)
    if resolved is None:
        logger.warning("DM storage-root 圍籬攔截一筆逃逸 / 無效之 FILE_PATH（不記路徑）")
        raise not_found
    return resolved
