"""文件廢止申請 API（US8 / UCDM05 / DM07）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色）+ 寫入注入 `get_operator`；發起廢止另要求 DM_EDITOR。
以 multipart 收廢止原因 / 指定審核者 / 選填單檔附件。核准 / 退回於簽核中心（US6 / DM02）處理。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo, get_operator
from app.core.schema_types import SAFE_MULTILINE_PATTERN, STRIP_BEFORE_VALIDATE
from app.dm.deps import DmContext, get_dm_context
from app.dm.document.file_store import enforce_size_limit
from app.dm.obsolete.schemas import InitiateObsoleteResult
from app.dm.obsolete.service import ObsoleteService
from app.dm.roles.authz import DM_EDITOR, has_role

router = APIRouter(prefix="/api/dm", tags=["dm-obsolete"])
_service = ObsoleteService()

#: 廢止申請原因上限（裁示 2026-10-17）。`DM_REVIEW.REASON` 是無界 `Text`，但此值會寫入
#: `DM_CHANGE_LOG.NOTE`（亦為無界 `Text`）與廢止相關通知。
#:
#: 為何是 500 而非更寬：廢止是 DM 唯一一個「申請時可附單檔」的路徑（下方的 `file`，用途註明
#: 「如函文 / 公文」）——長篇理由本來就該以公文附件呈現，自由文字欄位只放摘要。順帶與退回原因
#: 的 500（`review/schemas.RejectReq`）對齊。
#:
#: ⚠️ 附件採最小揭露（`review/center_service.prepare_obsolete_file`：僅 DM_ADMIN 或該送審之
#: 指定審核者可下載，發起人本人與一般閱覽者皆不可），所以**超過 500 字的內容，一般閱覽者永遠
#: 讀不到**。日後若有人覺得 500 太短想放寬，要先推翻的是附件的最小揭露裁示，不是這個數字。
_REASON_MAX = 500
#: 不套單行約束：廢止原因前端為 multiline，本來就該能多行；但仍要擋 NUL
#: （`Text` 欄位存不下，實測拋 `CharacterNotInRepertoireError` → 未攔截的 500）。
_ReasonForm = Annotated[
    str,
    STRIP_BEFORE_VALIDATE,
    Form(max_length=_REASON_MAX, pattern=SAFE_MULTILINE_PATTERN),
]

#: 指定審核者 user_id，對齊 `DM_REVIEW.ASSIGNED_REVIEWER` 的 `String(20)`。
#: service 的 `_ensure_assignable_reviewer` 會先查人、查不到就 422——那擋得住長度，
#: 但含 NUL 的值在查到「不存在」之前就會讓該查詢拋 `CharacterNotInRepertoireError`。
_ReviewerIdForm = Annotated[
    str,
    STRIP_BEFORE_VALIDATE,
    Form(max_length=20, pattern=SAFE_MULTILINE_PATTERN),
]


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
    reason: _ReasonForm = "",
    reviewer_id: _ReviewerIdForm = "",
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
