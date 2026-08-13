"""文件詳細頁 API（US4 / DM02，唯讀 + 下載記錄）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色）；閱覽者結果 / 檔案由 service 套可見性存取控制。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dm.deps import DmContext, get_dm_context
from app.dm.detail.schemas import DetailResponse, VersionItem
from app.dm.detail.service import DetailService

router = APIRouter(prefix="/api/dm/documents", tags=["dm-detail"])
_service = DetailService()


@router.get("/{doc_id}", response_model=DetailResponse)
async def get_document_detail(
    doc_id: str,
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """文件詳細（目前發布版）：標題 + 資訊面板 + 檔案 meta + can_edit + 廢止資訊；套存取控制。"""
    return await _service.get_detail(db, doc_id=doc_id, ctx=ctx)


@router.get("/{doc_id}/versions", response_model=list[VersionItem])
async def get_document_versions(
    doc_id: str,
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """版本歷程：所有版本（發布時間 DESC）；標示目前版（可下載）vs 舊版（僅預覽）。"""
    return await _service.list_versions(db, doc_id=doc_id, ctx=ctx)


@router.get("/{doc_id}/versions/{version_id}/file")
async def get_version_file(
    doc_id: str,
    version_id: int,
    disposition: Literal["preview", "download"] = Query(default="download"),
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """檔案存取：PDF/圖片可 preview（inline）；download 僅限目前發布版（寫 DM_DOC_READ），舊版下載 403。"""
    served = await _service.prepare_file(db, doc_id=doc_id, version_id=version_id, disposition=disposition, ctx=ctx)
    return FileResponse(
        served.path,
        media_type=served.mime,
        filename=served.name,
        content_disposition_type="inline" if served.inline else "attachment",
    )
