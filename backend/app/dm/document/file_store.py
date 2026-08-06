"""檔案儲存服務（T016）。

檔案存檔案系統 / 物件儲存，DB 僅存 metadata（FILE_*）。上傳前檢核大小（讀平台
`DP_PARAM.DM_FILE_MAX_MB`）與格式（`DM_FILE_TYPES`）。依 MIME 判定可預覽（PDF / 圖片）
或僅下載（Office）。研究 §3 / §10。

實際落盤 I/O（寫檔案系統 / 物件儲存）屬部署層，Foundation 提供可測核心：預覽判定 + 上傳檢核。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.services import ParamService

_MB = 1024 * 1024
_DEFAULT_MAX_MB = 50

# 可內嵌預覽之 MIME（其餘如 Office 僅提供下載）
_PREVIEWABLE_MIMES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/gif"})


def is_previewable(mime: str) -> bool:
    """MIME 是否可內嵌預覽（PDF / 圖片）；Office 等回 False（僅下載）。"""
    return mime.lower() in _PREVIEWABLE_MIMES


async def validate_upload(
    db: AsyncSession, *, size_bytes: int, filename: str, params: ParamService | None = None
) -> None:
    """上傳前檢核：大小不逾 `DM_FILE_MAX_MB`、副檔名屬 `DM_FILE_TYPES`。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）、不支援格式（422 DM_FILE_002）。
    """
    svc = params or ParamService()
    max_mb = await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", _DEFAULT_MAX_MB)
    if size_bytes > max_mb * _MB:
        raise AppError(status_code=422, detail="檔案大小超過上限", error_code="DM_FILE_001")

    allowed = await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE")
    if allowed:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed_set = {t.strip().lower() for t in allowed.split(",") if t.strip()}
        if ext not in allowed_set:
            raise AppError(status_code=422, detail="不支援的檔案格式", error_code="DM_FILE_002")
