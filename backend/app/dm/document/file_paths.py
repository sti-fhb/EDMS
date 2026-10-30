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
    """檔案儲存根目錄之正規化絕對路徑（單一事實來源：settings.DM_FILE_STORAGE_ROOT）。

    空設定值 fail-closed（#240 A4）：`os.path.realpath("")` 回 CWD，圍籬範圍會變成整個後端
    原始碼目錄。production 由 config 護欄於啟動即擋，dev（DEBUG=true）則靠此處。
    """
    value = settings.DM_FILE_STORAGE_ROOT
    if not value or not value.strip():
        raise RuntimeError("DM_FILE_STORAGE_ROOT 未設定，拒絕以工作目錄作為檔案儲存根目錄")
    return os.path.realpath(value)


def _resolved_within_root(path: str, root: str | None = None) -> str | None:
    """path 以 storage root 為基準正規化（解析 `..` / symlink）後若落在 root 內回其 canonical 絕對路徑，否則 None。

    `path` 為**相對於 storage root 的片段**（`DM_DOC_VERSION.FILE_PATH` 之儲存格式，#233）；
    傳入絕對路徑亦受支援——`os.path.join` 遇絕對第二引數會丟棄 root 直接回該路徑，故既有
    絕對路徑資料只要仍落在當前 root 內即照常解析（免 big-bang 轉換）。

    ⚠️ 上述 join 行為使絕對路徑得以繞過 root 前綴，**其後的 commonpath 檢查是唯一防線**——
    移除它等同解除圍籬（root 外之絕對路徑注入將直接放行）。重構時不得省略。

    fail-closed：None / 空字串 / 非字串、跨磁碟（Windows commonpath ValueError）、逃出根目錄一律回 None。
    單次 realpath——回傳值即「被驗證且將被串流」的同一路徑（避免 validate 與 serve 取不同解析）。
    """
    if not isinstance(path, str) or not path:
        return None
    root = storage_root() if root is None else root
    try:
        resolved = os.path.realpath(os.path.join(root, path))
        return resolved if os.path.commonpath([root, resolved]) == root else None
    except (ValueError, TypeError):
        return None


def is_within_root(path: str) -> bool:
    """path 正規化後是否落在 storage root 內（fail-closed，見 `_resolved_within_root`）。"""
    return _resolved_within_root(path) is not None


def _belongs_to(resolved: str, prefix: str, root: str) -> bool:
    """已通過 root 圍籬之 `resolved` 是否位於 `{root}/{prefix}/` 之下（不含該目錄本身）。

    以**解析後**路徑相對於 root 的第一段比對，而非比對原始字串——`..` 繞道、symlink 指向他份
    文件、既有絕對路徑資料因此一併被涵蓋。空 `prefix` 不會等於任何一段，自然 fail-closed。
    """
    parts = os.path.relpath(resolved, root).split(os.sep)
    return len(parts) >= 2 and parts[0] == prefix


def resolve_within_root(file_path: str, *, not_found: AppError, expect_prefix: str | None = None) -> str:
    """讀取端 storage-root 圍籬：回正規化後之安全路徑；逃逸出根目錄 → raise 呼叫端提供之 `not_found`。

    防禦深度——即使 `DM_DOC_VERSION.FILE_PATH` 因落盤層瑕疵含 `../` / 絕對路徑逃逸，串流端亦不外洩
    根目錄外檔案（讀取者可能為最低權限閱覽者 / 無 DM 角色之 ET 學員）。錯誤文案由各模組 `not_found`
    自帶（避免與該端點其他 404 措辭不一致）。逃逸時記安全事件（**不記落盤路徑**，遵 sti-backend-logging）。

    `expect_prefix`（#240 A1）：傳入時另驗檔案落在 `{root}/{expect_prefix}/` 之下。授權以 `doc_id`
    判定，檔案邊界須對齊同一個 `doc_id`——否則一筆寫錯的 `FILE_PATH` 就能讓持有 A 文件閱覽權者讀到
    B 文件。此為 root 圍籬之**額外**一層，root 圍籬一律先跑、不可被取代。兩層共用同一次取得的 root，
    避免兩次 `realpath` 之間 root 被換掉而各驗各的。
    """
    root = storage_root()
    resolved = _resolved_within_root(file_path, root)
    if resolved is None:
        logger.warning("DM storage-root 圍籬攔截一筆逃逸 / 無效之 FILE_PATH（不記路徑）")
        raise not_found
    if expect_prefix is not None and not _belongs_to(resolved, expect_prefix, root):
        logger.warning("DM 檔案歸屬圍籬攔截一筆不屬於本文件之 FILE_PATH（不記路徑）")
        raise not_found
    return resolved
