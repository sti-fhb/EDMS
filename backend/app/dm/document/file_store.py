"""檔案儲存服務（T016）。

檔案存檔案系統 / 物件儲存，DB 僅存 metadata（FILE_*）。上傳前檢核大小（讀平台
`DP_PARAM.DM_FILE_MAX_MB`）與格式（`DM_FILE_TYPES`）。依 MIME 判定可預覽（PDF / 圖片）
或僅下載（Office）。研究 §3 / §10。

實際落盤 I/O（寫檔案系統 / 物件儲存）屬部署層，Foundation 提供可測核心：預覽判定 + 上傳檢核。

⚠️ 安全契約：
- 副檔名白名單檢核**非充分條件**——故 `resolve_upload_mime` 另以 magic bytes 驗證可預覽類之真實型別、
  並以伺服端判定之權威 MIME 落地（防 evil.exe 改名 evil.pdf 之內嵌 XSS，T066 M2）。
- 檔名不得用於組路徑：一律以系統產生之 FILE_ID 命名，避免 `../` 路徑穿越。
- `DM_FILE_TYPES` 參數若被清空 / 停用，本函式**改用安全預設白名單 fail-closed**（不再跳過格式檢核），
  避免管理者誤清參數即開放任意副檔名（T066 L2）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.services import ParamService

_MB = 1024 * 1024
_DEFAULT_MAX_MB = 50

# 可內嵌預覽之 MIME（其餘如 Office 僅提供下載）
_PREVIEWABLE_MIMES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/gif"})

# 安全預設副檔名白名單（fail-closed）：DM_FILE_TYPES 參數缺值時的後備，對齊種子預設值。
_DEFAULT_FILE_TYPES = frozenset({"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "jpg", "jpeg", "png"})


def is_previewable(mime: str) -> bool:
    """MIME 是否可內嵌預覽（PDF / 圖片）；Office 等回 False（僅下載）。"""
    return mime.lower() in _PREVIEWABLE_MIMES


# 副檔名 → 權威 MIME（**伺服端判定、完全不採用戶端 content_type**）。可預覽類（前 5 項）另需 magic 驗證。
_EXT_TO_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# 可內嵌預覽副檔名（須 magic 驗證真實型別）；其權威 MIME 見 _EXT_TO_MIME。
_PREVIEWABLE_EXTS = frozenset({"pdf", "png", "jpg", "jpeg", "gif"})


def sniff_previewable_mime(head: bytes) -> str | None:
    """由檔頭 magic bytes 判定是否為可內嵌預覽型別（PDF/PNG/JPEG/GIF）；非上述回 None。"""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def resolve_upload_mime(file_bytes: bytes, filename: str) -> str:
    """**伺服端**由副檔名 + magic bytes 判定落地 MIME，**完全不採用戶端 content_type**（T066 M2）。

    不變量：**回傳之 MIME 為可預覽 ⟺ 已 magic-byte 驗證**。
    - 落地 MIME 一律取 `_EXT_TO_MIME[ext]`（白名單映射；未知副檔名 → `application/octet-stream`）——杜絕
      用戶端謊報 MIME（含謊報 `text/html` / `image/svg+xml` 等非可預覽但可渲染型別）寫入 DB。
    - 可預覽類副檔名（pdf/png/jpg/jpeg/gif）另要求檔頭 magic 為對應型別，否則 `DM_FILE_002`（真實型別
      與副檔名不符，防 evil.exe 改名 evil.pdf 之內嵌 XSS）。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime = _EXT_TO_MIME.get(ext, "application/octet-stream")
    if ext in _PREVIEWABLE_EXTS and sniff_previewable_mime(file_bytes[:16]) != mime:
        raise AppError(status_code=422, detail="檔案內容與副檔名不符", error_code="DM_FILE_002")
    return mime


async def resolve_upload_limits(db: AsyncSession, *, params: ParamService | None = None) -> tuple[int, frozenset[str]]:
    """目前生效的 `(單檔上限 MB, 允許副檔名集合)`。

    ## 🔴 這是**唯一**的解析處——驗證與「告訴使用者能傳什麼」都走它（#455）

    改版前上傳畫面的文案與 `accept` 是**寫死**的，於是 IT 依既定途徑改了 `DP_PARAM`
    之後，DP07 顯示新值、上傳畫面仍說舊話，而 `accept` 還會把新允許的格式擋在選檔器
    外——使用者看到的是「這個格式不能選」，**不會有任何錯誤訊息告訴他為什麼**。

    ⛔ **不要為前端另寫一支「取得限制」的函式。** 兩支各自解析參數、各自決定 fallback，
    遲早分岔——而分岔的表徵正是本 issue 要修的那個病：**選得到卻傳不上去**（或相反）。

    ⚠️ fail-closed 的語意必須保留：`DM_FILE_TYPES` 缺值 / 清空時退回**安全預設白名單**，
    而不是「全部放行」。管理者誤清參數不該等於開放任意副檔名（T066 L2）。
    """
    svc = params or ParamService()
    max_mb = await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", _DEFAULT_MAX_MB)
    allowed = await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE")
    allowed_set = frozenset(t.strip().lower() for t in (allowed or "").split(",") if t.strip())
    return max_mb, (allowed_set or _DEFAULT_FILE_TYPES)


async def enforce_size_limit(db: AsyncSession, *, size_bytes: int, params: ParamService | None = None) -> None:
    """僅檢核大小不逾 `DM_FILE_MAX_MB`（供 router 於 `read()` 前以 `UploadFile.size` 先擋，避免整包載入記憶體）。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）。
    """
    svc = params or ParamService()
    max_mb = await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", _DEFAULT_MAX_MB)
    if size_bytes > max_mb * _MB:
        raise AppError(status_code=422, detail="檔案大小超過上限", error_code="DM_FILE_001")


async def validate_upload(
    db: AsyncSession, *, size_bytes: int, filename: str, params: ParamService | None = None
) -> None:
    """上傳前檢核：大小不逾 `DM_FILE_MAX_MB`、副檔名屬 `DM_FILE_TYPES`。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）、不支援格式（422 DM_FILE_002）。
    """
    svc = params or ParamService()
    await enforce_size_limit(db, size_bytes=size_bytes, params=svc)

    # fail-closed：DM_FILE_TYPES 缺值 / 清空 → 退回安全預設白名單，格式檢核恆執行（T066 L2）
    #
    # ⚠️ 允許集合由 `resolve_upload_limits` 解析——**前端的 `accept` 走的是同一支**，
    # 兩邊因此不可能分岔（#455）。
    _, allowed_set = await resolve_upload_limits(db, params=svc)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_set:
        raise AppError(status_code=422, detail="不支援的檔案格式", error_code="DM_FILE_002")
