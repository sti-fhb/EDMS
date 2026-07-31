"""排程總覽端點（US11 / dp-schedule，唯讀）。

授權：依 [sti-backend-modules 暫行授權規則] 僅掛 router-level get_jwt_payload 認證（暫行案 A、同
dp-audit）；真 admin 閘待 T049 回歸重用 DP_AUTH_006。共用項（不分模組）。**無啟停 / 補跑端點**
（啟停由 DB / 部署管理，FR-06）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_payload
from app.core.db import get_db
from app.core.pagination import MAX_LIMIT, PagedResponse, paginate
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.schemas import ScheduleLogResponse, ScheduleResponse

router = APIRouter(prefix="/api/dp/schedules", tags=["dp-schedule"], dependencies=[Depends(get_jwt_payload)])

_repo = ScheduleRepository()


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(db: AsyncSession = Depends(get_db)) -> list[ScheduleResponse]:
    """排程 job 清單（唯讀；含停用；資料量 < 10 筆不分頁）。"""
    jobs = await _repo.list_all(db)
    return [ScheduleResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}/logs", response_model=PagedResponse[ScheduleLogResponse])
async def list_schedule_logs(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
):
    """某 job 之執行歷程（後端分頁、時間倒序）。"""
    return await paginate(db, _repo.build_logs_stmt(job_id), page=page, limit=limit, schema=ScheduleLogResponse)
