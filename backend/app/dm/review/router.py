"""簽核中心 API（US6 / DM04）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色）+ 寫入注入 `get_operator`；核准 / 退回 / 明細僅
指定審核者本人可操作（service 層以 `DM_REVIEW_005` 把關）。清單依 `assigned_reviewer=登入者` 過濾。
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse
from app.dm.deps import DmContext, get_dm_context
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.schemas import (
    ApproveResult,
    CompletedItem,
    PendingItem,
    RejectReq,
    RejectResult,
    ReviewDetail,
)

router = APIRouter(prefix="/api/dm/reviews", tags=["dm-review"])
_service = ReviewCenterService()


@router.get("/pending", response_model=list[PendingItem])
async def list_pending(
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """待簽核清單：指派給自己之 PENDING（停留最久在前）。"""
    return await _service.list_pending(db, op=op)


@router.get("/completed", response_model=PagedResponse[CompletedItem])
async def list_completed(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default="", max_length=200),
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """已完成頁籤：自己過往核准 / 退回（完成時間 DESC、後端分頁、文件名搜尋、不可再操作）。"""
    return await _service.list_completed(db, op=op, page=page, limit=limit, keyword=keyword)


@router.get("/{review_id}", response_model=ReviewDetail)
async def get_detail(
    review_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """簽核明細（僅指定審核者本人；新版本附目前發布版供比對）。"""
    return await _service.get_detail(db, review_id=review_id, op=op)


@router.get("/{review_id}/versions/{version_id}/file")
async def download_review_file(
    review_id: int,
    version_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """簽核明細下載：僅指定審核者本人，且僅限本送審之待審版 / 目前發布版（供新舊比對）。"""
    served = await _service.prepare_file(db, review_id=review_id, version_id=version_id, op=op)
    # 實體檔缺失（DB↔磁碟不一致）：回統一 404，避免 FileResponse 拋出含落盤路徑的 500（不洩路徑）。
    if not Path(served.path).is_file():
        raise AppError(status_code=404, detail="查無此送審項目或無權存取", error_code="DM_DOC_001")
    return FileResponse(
        served.path, media_type=served.mime, filename=served.name, content_disposition_type="attachment"
    )


@router.get("/{review_id}/obsolete-file")
async def download_obsolete_file(
    review_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """廢止附件下載（US8）：僅 DM_ADMIN 或該送審之指定審核者（SA 裁示 Q1=C）。"""
    served = await _service.prepare_obsolete_file(db, review_id=review_id, roles=ctx.roles, op=op)
    if not Path(served.path).is_file():
        raise AppError(status_code=404, detail="查無此送審項目或無權存取", error_code="DM_DOC_001")
    return FileResponse(
        served.path, media_type=served.mime, filename=served.name, content_disposition_type="attachment"
    )


@router.post("/{review_id}/approve", response_model=ApproveResult)
async def approve(
    review_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """核准並發布（NEW / NEW_VERSION）：版本切換 + 變更歷程 + DOC_PUBLISH 通知。"""
    return await _service.approve(db, review_id=review_id, op=op)


@router.post("/{review_id}/reject", response_model=RejectResult)
async def reject(
    review_id: int,
    body: RejectReq,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
):
    """退回：必填原因 → 版本 REJECTED、首版文件回 DRAFT、DOC_REJECT 通知撰寫者。"""
    return await _service.reject(db, review_id=review_id, reason=body.reason, op=op)
