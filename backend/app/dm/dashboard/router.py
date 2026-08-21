"""系統儀表板 API（US7 / DM00）。

掛 DM 存取閘 `get_dm_context`（需任一 DM 角色，FR-001 所有可進入 DM 者皆可瀏覽）；純讀取、無寫入。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dm.dashboard.schemas import AnnouncementItem, DashboardStats
from app.dm.dashboard.service import DashboardService
from app.dm.deps import DmContext, get_dm_context

router = APIRouter(prefix="/api/dm/dashboard", tags=["dm-dashboard"])
_service = DashboardService()


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """各類型文件總數：4 內建分類之已發布目前版本數 + 總計（FR-002）。"""
    return await _service.get_stats(db, user_id=ctx.user_id, roles=ctx.roles)


@router.get("/announcements", response_model=list[AnnouncementItem])
async def get_announcements(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
):
    """最新更新公告：近 30 天已發布（新增/新版本），發布時間 DESC；無事件回空清單（FR-003/004）。"""
    return await _service.get_announcements(db, user_id=ctx.user_id, roles=ctx.roles)
