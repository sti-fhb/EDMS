"""操作記錄查詢端點（US10 / dp-audit，唯讀）。

授權：router-level 掛 `require_any_module_admin()`——需 ET 或 DM 任一模組管理者，
落地 spec_us10「作為 ET 或 DM 管理者」與稽核「僅管理者」（AUDIT-002）。#250 起生效：
此前為 interim「對所有登入者開放、以未登入 401 先行」，即當時註記「待 T049 隨
is_module_admin 回歸」之真 admin 閘。**不提供任何刪改端點**（append-only）。
"""

from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.module_admin import require_any_module_admin
from app.core.pagination import MAX_LIMIT, PagedResponse
from app.core.utils import format_taipei_date, utcnow
from app.dp.audit.query_service import (
    ACTION_OPTIONS,
    FUNC_OPTIONS,
    MODULE_OPTIONS,
    RESULT_OPTIONS,
    AuditQueryService,
)
from app.dp.audit.schemas import AuditLogResponse, AuditOptionsResponse

router = APIRouter(prefix="/api/dp/audit", tags=["dp-audit"], dependencies=[Depends(require_any_module_admin())])

_service = AuditQueryService()

_Module = Literal["DP", "ET", "DM"]
# ⚠️ 必須涵蓋所有**寫得進去**的 action_type，否則該值在下拉選得到、查詢卻被擋成 422。
# `EXPORT` 於 #322 導入時只補了兩處 label、漏了此處與種子清單，直到 #477 才發現。
# 新增值時一併檢查：query_service._ACTION_LABELS 與 DP_PARAM.ACTION_TYPE 種子
# （前端自 #477 起經 /options 取得，無需另行維護）。
_Action = Literal["LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE", "EXPORT"]
_Result = Literal["SUCCESS", "FAIL"]


@router.get("/options", response_model=AuditOptionsResponse)
async def get_audit_options() -> AuditOptionsResponse:
    """回四組篩選下拉選項（功能 / 操作類別 / 執行結果 / 模組）。

    純靜態對照、不查 DB，故無 `db` 參數。授權由 router-level 的 `require_any_module_admin()`
    承擔——選項本身雖不含業務資料，但會洩露系統有哪些功能模組，與查詢端點同級保護。
    """
    return AuditOptionsResponse(
        func_options=FUNC_OPTIONS,
        action_options=ACTION_OPTIONS,
        result_options=RESULT_OPTIONS,
        module_options=MODULE_OPTIONS,
    )


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


def _export_filename(now: datetime) -> str:
    """匯出檔名 `audit_log_YYYYMMDD.csv`，日期取**台灣時間**。

    抽成純函式**是為了讓它測得到**：原本內嵌在 handler 裡，要驗它得連真 DB 跑完整個匯出。

    原寫法是 `datetime.now(timezone.utc).strftime('%Y%m%d')`，於台灣 00:00–08:00 匯出時
    會命名成前一天——與檔案內容的時間欄、以及查詢頁以台灣時間切日的日期篩選都對不上（#519）。

    Args:
        now: 當下時間（aware）。由呼叫端傳入而非在函式內取系統時間，否則無法測。
    """
    return f"audit_log_{format_taipei_date(now).replace('-', '')}.csv"


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
    filename = _export_filename(utcnow())
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
