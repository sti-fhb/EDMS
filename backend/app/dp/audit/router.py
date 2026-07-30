"""操作記錄查詢端點（US10 / dp-audit，唯讀）。

授權：依 [sti-backend-modules 暫行授權規則] 僅掛 router-level get_jwt_payload 認證
（SA 裁示 Q1=A）。稽核「僅管理者」（AUDIT-002）之真 admin 閘待 T049 隨 is_module_admin 回歸；
interim 對登入者開放、以「未登入 401」先行。**不提供任何刪改端點**（append-only）。
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_jwt_payload
from app.core.db import get_db
from app.core.pagination import MAX_LIMIT, PagedResponse
from app.dp.audit.query_service import AuditQueryService
from app.dp.audit.schemas import AuditLogResponse

router = APIRouter(prefix="/api/dp/audit", tags=["dp-audit"], dependencies=[Depends(get_jwt_payload)])

_service = AuditQueryService()

_Module = Literal["DP", "ET", "DM"]
_Action = Literal["LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE"]
_Result = Literal["SUCCESS", "FAIL"]


@router.get("/logs", response_model=PagedResponse[AuditLogResponse])
async def query_audit_logs(
    db: AsyncSession = Depends(get_db),
    operator: Optional[str] = Query(default=None, max_length=255),
    module: Optional[_Module] = Query(default=None),
    func_name: Optional[str] = Query(default=None, max_length=50),
    action_type: Optional[_Action] = Query(default=None),
    result: Optional[_Result] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
):
    """多條件查詢操作記錄（後端分頁、時間倒序）；稽核共用、兩管理者皆查全部。"""
    return await _service.query_logs(
        db,
        operator=operator,
        module=module,
        func_name=func_name,
        action_type=action_type,
        result=result,
        date_from=date_from,
        date_to=date_to,
        page=page,
        limit=limit,
    )


@router.get("/logs/export")
async def export_audit_logs(
    db: AsyncSession = Depends(get_db),
    operator: Optional[str] = Query(default=None, max_length=255),
    module: Optional[_Module] = Query(default=None),
    func_name: Optional[str] = Query(default=None, max_length=50),
    action_type: Optional[_Action] = Query(default=None),
    result: Optional[_Result] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
) -> Response:
    """依當前查詢條件全量匯出 CSV（無分頁）。"""
    content = await _service.export_csv(
        db,
        operator=operator,
        module=module,
        func_name=func_name,
        action_type=action_type,
        result=result,
        date_from=date_from,
        date_to=date_to,
    )
    filename = f"audit_log_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
