"""文件新增與編輯 API（US5 / DM03，寫入）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色）+ 寫入注入 `get_operator`；寫入型端點（新增 / 加版 /
送簽）另要求 **DM_EDITOR** 角色（`_ensure_editor`）。新增 / 加版以 multipart 收表單欄位 + 單一上傳檔。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context
from app.dm.editor.schemas import (
    CreateResult,
    EditorDocTags,
    EditorOptions,
    ReviewerItem,
    SubmitReq,
    SubmitResult,
    VersionResult,
)
from app.dm.editor.service import EditorService
from app.dm.roles.authz import DM_EDITOR, has_role

router = APIRouter(prefix="/api/dm", tags=["dm-editor"])
_service = EditorService()


def _ensure_editor(ctx: DmContext) -> None:
    """寫入型端點細粒度授權：須具文件編輯者角色（DM_EDITOR）。"""
    if not has_role(ctx.roles, DM_EDITOR):
        raise AppError(status_code=403, detail="需要文件編輯者權限", error_code="DM_AUTH_002")


@router.post("/documents", response_model=CreateResult, status_code=201)
async def create_document(
    doc_name: Annotated[str, Form()],
    category_code: Annotated[str, Form()],
    version_no: Annotated[str, Form()],
    change_summary: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    func_code: Annotated[str | None, Form()] = None,
    audience_ids: Annotated[list[int], Form()] = [],  # noqa: B006 (FastAPI 以此宣告 multipart 多值欄)
    retrieval_ids: Annotated[list[int], Form()] = [],  # noqa: B006
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """新增模式：建 DRAFT 文件（配 DOC_ID）+ DRAFT 首版 + 標籤。"""
    _ensure_editor(ctx)
    data = await file.read()
    return await _service.create_document(
        db,
        doc_name=doc_name,
        category_code=category_code,
        func_code=func_code,
        audience_ids=audience_ids,
        retrieval_ids=retrieval_ids,
        version_no=version_no,
        change_summary=change_summary,
        file_name=file.filename or "",
        file_bytes=data,
        file_mime=file.content_type or "application/octet-stream",
        op=op,
    )


@router.post("/documents/{doc_id}/versions", response_model=VersionResult, status_code=201)
async def add_version(
    doc_id: str,
    version_no: Annotated[str, Form()],
    change_summary: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    audience_ids: Annotated[list[int], Form()] = [],  # noqa: B006
    retrieval_ids: Annotated[list[int], Form()] = [],  # noqa: B006
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """編輯模式：既有文件加 DRAFT 版本（身份欄不吃）+ 覆寫文件層標籤（可見對象 / 檢索）。"""
    _ensure_editor(ctx)
    data = await file.read()
    return await _service.add_version(
        db,
        doc_id=doc_id,
        audience_ids=audience_ids,
        retrieval_ids=retrieval_ids,
        version_no=version_no,
        change_summary=change_summary,
        file_name=file.filename or "",
        file_bytes=data,
        file_mime=file.content_type or "application/octet-stream",
        op=op,
    )


@router.post("/documents/{doc_id}/submit", response_model=SubmitResult)
async def submit_document(
    doc_id: str,
    body: SubmitReq,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """送簽：建 review（NEW|NEW_VERSION）+ 狀態轉 PENDING_REVIEW + 通知審核者。"""
    _ensure_editor(ctx)
    return await _service.submit(
        db, doc_id=doc_id, version_id=body.version_id, assigned_reviewer=body.assigned_reviewer, op=op
    )


@router.get("/editor/documents/{doc_id}/tags", response_model=EditorDocTags)
async def get_document_tags(
    doc_id: str,
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """編輯模式預帶：文件現有可見對象 / 檢索標籤（TAG_ID）。"""
    return await _service.get_doc_tags(db, doc_id)


@router.get("/reviewers", response_model=list[ReviewerItem])
async def list_reviewers(
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """指定審核者下拉：具 DM_REVIEWER 角色之使用者（排除自己）。"""
    return await _service.list_reviewers(db, op=op)


@router.get("/editor/options", response_model=EditorOptions)
async def editor_options(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """DM03 表單受控下拉：分類 / func / 可見對象 / 檢索標籤（皆啟用中）。"""
    return await _service.get_options(db)
