"""檔案落盤路徑之 storage-root 圍籬（#160）。

讀 / 寫端共用同一根目錄常數（`settings.DM_FILE_STORAGE_ROOT`）與圍籬邏輯，避免上傳端與串流端 drift。
獨立為 leaf 模組（僅依賴 `os` / `settings` / `AppError`），不引入 `app.services`，避免與 `file_store`
（→ `app.services` → DM integration Service）形成循環 import。
"""

import os

from app.core.config import settings
from app.core.exceptions import AppError


def storage_root() -> str:
    """檔案儲存根目錄之正規化絕對路徑（單一事實來源：settings.DM_FILE_STORAGE_ROOT）。"""
    return os.path.realpath(settings.DM_FILE_STORAGE_ROOT)


def is_within_root(path: str) -> bool:
    """path 正規化（解析 `..` / symlink）後是否落在 storage root 內。

    跨磁碟（Windows，如 C: vs D:）→ commonpath 拋 ValueError → 視為逃逸回 False。
    """
    root = storage_root()
    try:
        resolved = os.path.realpath(path)
        return os.path.commonpath([root, resolved]) == root
    except ValueError:
        return False


def resolve_within_root(file_path: str) -> str:
    """讀取端 storage-root 圍籬：回正規化後之安全路徑；逃逸出根目錄 → AppError 404（不洩落盤路徑）。

    防禦深度——即使 `DM_DOC_VERSION.FILE_PATH` 因落盤層瑕疵含 `../` / 絕對路徑逃逸，串流端亦不外洩
    根目錄外檔案（讀取者可能為最低權限閱覽者 / 無 DM 角色之 ET 學員）。
    """
    if not is_within_root(file_path):
        raise AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")
    return os.path.realpath(file_path)
