"""排程總覽 / 編輯端點（US11 / dp-schedule）。

授權：依 [sti-backend-modules 暫行授權規則] 僅掛 router-level get_jwt_payload 認證（暫行案 A、同
dp-audit）；真 admin 閘待 T049 回歸重用 DP_AUTH_006。共用項（不分模組）。
編輯僅開放 JOB_NAME / CRON_EXPR / IS_ENABLED；**不提供手動補跑端點**（補跑各模組自理，FR-03）、
**HANDLER_REF / MODULE 不可改**（RCE 防護）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_payload
from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import MAX_LIMIT, PagedResponse, paginate
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.schemas import ScheduleLogResponse, ScheduleResponse, ScheduleUpdate
from app.dp.schedules.service import ScheduleService

router = APIRouter(prefix="/api/dp/schedules", tags=["dp-schedule"], dependencies=[Depends(get_jwt_payload)])

_repo = ScheduleRepository()
_service = ScheduleService()


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(db: AsyncSession = Depends(get_db)) -> list[ScheduleResponse]:
    """排程 job 清單（含停用；含由 cron 計算之下次執行時間；資料量 < 10 筆不分頁）。"""
    return await _service.list_jobs(db)


@router.put("/{job_id}", response_model=ScheduleResponse)
async def update_schedule(
    job_id: str,
    data: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """編輯排程（JOB_NAME / CRON_EXPR / IS_ENABLED）；cron 即時生效、寫稽核。"""
    return await _service.update_job(db, job_id=job_id, data=data, operator=operator)


@router.get("/{job_id}/logs", response_model=PagedResponse[ScheduleLogResponse])
async def list_schedule_logs(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
):
    """某 job 之執行歷程（後端分頁、時間倒序）。"""
    return await paginate(db, _repo.build_logs_stmt(job_id), page=page, limit=limit, schema=ScheduleLogResponse)
