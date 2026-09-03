"""檔案儲存服務（T016）。

檔案存檔案系統 / 物件儲存，DB 僅存 metadata（FILE_*）。上傳前檢核大小（讀平台
`DP_PARAM.DM_FILE_MAX_MB`）與格式（`DM_FILE_TYPES`）。依 MIME 判定可預覽（PDF / 圖片）
或僅下載（Office）。研究 §3 / §10。

實際落盤 I/O（寫檔案系統 / 物件儲存）屬部署層，Foundation 提供可測核心：預覽判定 + 上傳檢核。

⚠️ 安全契約（落盤層須遵守，見 sti-backend-ref 待補）：
- 副檔名白名單檢核**非充分條件**——落盤前應另以 content-type / magic bytes 驗證真實型別
  （防 evil.exe 改名 evil.pdf）。
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


# 可內嵌預覽副檔名 → 其權威 MIME（magic-byte 驗證用）。Office / 壓縮類簽章弱且非可預覽，不列入。
_EXT_TO_PREVIEWABLE_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}


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


def resolve_upload_mime(file_bytes: bytes, filename: str, declared_mime: str | None) -> str:
    """伺服端判定落地 MIME，杜絕「可預覽 MIME 未經 magic 驗證即內嵌」之 XSS/MIME sniffing 面（T066 M2）。

    不變量：**回傳之 MIME 為可預覽 ⟺ 已 magic-byte 驗證**。
    - 副檔名屬可預覽類（pdf/png/jpg/jpeg/gif）：檔頭 magic 必須為對應型別，否則 `DM_FILE_002`（真實型別
      與副檔名不符，防 evil.exe 改名 evil.pdf）；回**伺服端判定之權威 MIME**（不採用戶端 content_type）。
    - 其餘（Office 等非可預覽）：不強制 magic（其簽章弱、且一律僅下載不內嵌）；但**剝除**用戶端謊報的
      可預覽 MIME（改回 `application/octet-stream`），確保非驗證檔不會被當可預覽內嵌。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected = _EXT_TO_PREVIEWABLE_MIME.get(ext)
    if expected is not None:
        if sniff_previewable_mime(file_bytes[:16]) != expected:
            raise AppError(status_code=422, detail="檔案內容與副檔名不符", error_code="DM_FILE_002")
        return expected
    declared = (declared_mime or "").lower()
    return declared_mime if declared and not is_previewable(declared) else "application/octet-stream"


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
    allowed = await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE")
    allowed_set = {t.strip().lower() for t in (allowed or "").split(",") if t.strip()} or _DEFAULT_FILE_TYPES
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_set:
        raise AppError(status_code=422, detail="不支援的檔案格式", error_code="DM_FILE_002")
