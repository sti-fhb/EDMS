"""文件廢止申請 API（US8 / UCDM05 / DM02）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色）+ 寫入注入 `get_operator`；發起廢止另要求 DM_EDITOR。
以 multipart 收廢止原因 / 指定審核者 / 選填單檔附件。核准 / 退回於簽核中心（US6 / DM04）處理。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context
from app.dm.document.file_store import enforce_size_limit
from app.dm.obsolete.schemas import InitiateObsoleteResult
from app.dm.obsolete.service import ObsoleteService
from app.dm.roles.authz import DM_EDITOR, has_role

router = APIRouter(prefix="/api/dm", tags=["dm-obsolete"])
_service = ObsoleteService()


def _ensure_editor(ctx: DmContext) -> None:
    """發起廢止細粒度授權：須具文件編輯者角色（DM_EDITOR）。"""
    if not has_role(ctx.roles, DM_EDITOR):
        raise AppError(status_code=403, detail="需要文件編輯者權限", error_code="DM_AUTH_002")


async def _read_upload(db: AsyncSession, file: UploadFile | None) -> tuple[str | None, bytes | None, str | None]:
    """讀取選填廢止附件 → (檔名, bytes, mime)；未附檔回 (None, None, None)。

    M1：`read()` 前先以 `UploadFile.size` 對照大小上限先擋，避免過大 body 整包載入記憶體（認證後 DoS）。
    """
    if file is None:
        return None, None, None
    if file.size is not None:
        await enforce_size_limit(db, size_bytes=file.size)
    return file.filename or "", await file.read(), file.content_type or "application/octet-stream"


@router.post("/documents/{doc_id}/obsolete", response_model=InitiateObsoleteResult)
async def initiate_obsolete(
    doc_id: str,
    reason: Annotated[str, Form()] = "",
    reviewer_id: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,  # 選填單檔廢止附件（如函文 / 公文）
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> InitiateObsoleteResult:
    """發起整份文件廢止申請：文件轉廢止待簽核並通知指定審核者。"""
    _ensure_editor(ctx)
    file_name, data, file_mime = await _read_upload(db, file)
    return await _service.initiate(
        db,
        doc_id=doc_id,
        reason=reason,
        reviewer_id=reviewer_id,
        file_name=file_name,
        file_bytes=data,
        file_mime=file_mime,
        op=op,
    )
