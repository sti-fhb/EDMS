"""DM 文件上傳落盤（US5 / T038）。

#127 `file_store` 只做上傳「檢核」（大小 / 副檔名）與預覽判定，實際 byte 落盤留待此層。
本層將上傳位元組寫入設定的儲存根目錄（`settings.DM_FILE_STORAGE_ROOT`），以**系統產生之
`FILE_ID`** 命名（不用原始檔名組路徑，防 `../` 路徑穿越），回傳**相對於該根目錄**之
`FILE_PATH` 供 `DM_DOC_VERSION.FILE_PATH` 記錄、US4 檔案端點串流（#233：改存相對路徑，
使資料可隨 root 搬移；存絕對路徑會在換 worktree / 換機器時全數失聯）。

⚠️ 讀取端 storage-root 圍籬（解析後路徑須落在根內）為 #160 follow-up；本層先確保**寫入**
一律落在根下、檔名不含使用者輸入。
"""

import os
import uuid

from app.dm.document.file_paths import is_within_root, storage_root

# 副檔名白名單（與 DM_FILE_TYPES 語意一致；用於由原始檔名安全萃取副檔名，不接受其他字元）
_ALLOWED_EXT_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789")


def generate_file_id() -> str:
    """產生檔案識別碼（隨機、不可猜、供落盤檔名，避免以原始檔名組路徑）。"""
    return uuid.uuid4().hex


def _safe_ext(filename: str) -> str:
    """由原始檔名安全萃取副檔名（僅小寫英數，最長 10）；無 / 不合法則回空字串。"""
    if "." not in filename:
        return ""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext and len(ext) <= 10 and all(c in _ALLOWED_EXT_CHARS for c in ext):
        return ext
    return ""


def save_upload(*, doc_id: str, file_id: str, filename: str, data: bytes) -> str:
    """將上傳位元組寫入 `{root}/{doc_id}/{file_id}.{ext}`，回傳**相對於 root** 的 `FILE_PATH`。

    Args:
        doc_id: 所屬文件（作為子目錄，便於管理與日後清理）。
        file_id: 系統產生之檔案識別碼（檔名主體）。
        filename: 原始檔名（僅用於萃取副檔名，不入路徑）。
        data: 檔案位元組。

    Returns:
        `{doc_id}/{file_id}.{ext}`——相對於 storage root 之片段，供 DB `FILE_PATH` 記錄。
        分隔符固定 `/`（`os.sep` 在 Windows 為 `\\`，該值搬到 POSIX 即讀不到，因為 `\\`
        在 POSIX 是合法檔名字元而非分隔符）。

        回傳值由**已通過圍籬檢查的絕對路徑**經 `relpath` 反推，而非另行以原始 `doc_id`
        組字串——後者會讓「被驗證的物件」與「落 DB 的物件」是兩個不同的東西，日後任一端
        重構就可能靜默產生落差。

    Note:
        落盤仍以絕對路徑進行（`makedirs` / `open` 需要），改的只是**寫進 DB 的值**——
        存絕對路徑會把 `FILE_PATH` 綁死在當下的機器與工作目錄，worktree 一被 `/sti-cleanup`
        清掉即永久失聯，且無法以複製檔案救回（讀取端圍籬會擋在檔案存在性檢查之前）。見 #233。
    """
    root = storage_root()  # 與讀取端圍籬共用同一根目錄常數（file_store，避免 drift，#160）
    ext = _safe_ext(filename)
    name = f"{file_id}.{ext}" if ext else file_id
    path = os.path.abspath(os.path.join(root, doc_id, name))
    doc_dir = os.path.dirname(path)
    # 圍籬（防禦深度、不依賴呼叫端）：解析後之目錄與檔案路徑一律須落在 root 內，
    # 否則視為受污染之 doc_id / file_id 之路徑穿越，拒絕落盤。
    if not is_within_root(path) or not is_within_root(doc_dir):
        raise ValueError("不合法的落盤路徑（疑似路徑穿越）")
    os.makedirs(doc_dir, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return os.path.relpath(path, root).replace(os.sep, "/")
