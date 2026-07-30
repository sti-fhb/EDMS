"""稽核查詢 / 匯出服務（US10 / dp-audit，唯讀）。

與寫入服務（AuditLogService / SRVDP003）刻意分離：本服務僅 SELECT，不提供任何刪改。
稽核為**共用項**——不做 MODULE 過濾，`module` 僅為使用者選填之查詢條件（兩管理者皆查全部）。
"""

import csv
import io
from datetime import date, datetime

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResult
from app.dp.audit.repository import AuditLogRepository, build_audit_conditions
from app.dp.audit.schemas import AuditLogResponse

# CSV 欄位（欄位名 → 標頭），與列表 / 明細一致 + 前後值。
_CSV_COLUMNS: list[tuple[str, str]] = [
    ("log_id", "LOG_ID"),
    ("created_date", "時間"),
    ("operator_id", "操作者 ID"),
    ("operator_name", "操作者"),
    ("module", "模組"),
    ("func_name", "功能"),
    ("action_type", "操作類別"),
    ("result", "執行結果"),
    ("target_id", "對象"),
    ("source_ip", "來源 IP"),
    ("description", "事件描述"),
    ("before_value", "異動前值"),
    ("after_value", "異動後值"),
]

# 可觸發試算表公式注入的前導字元（含 tab / CR）。
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _format_value(field: str, value: object) -> str:
    """欄位值 → CSV 字串（時間格式化至秒；None → 空字串）。"""
    if value is None:
        return ""
    if field == "created_date" and isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _sanitize_csv_cell(text: str) -> str:
    """CSV formula injection 防護：以危險字元開頭者前置單引號，令試算表視為文字。"""
    if text and text[0] in _CSV_INJECTION_PREFIXES:
        return "'" + text
    return text


class AuditQueryService:
    """稽核多條件查詢 + CSV 匯出（唯讀）。"""

    def __init__(self, repository: AuditLogRepository | None = None) -> None:
        self._repo = repository or AuditLogRepository()

    async def query_logs(
        self,
        db: AsyncSession,
        *,
        operator: str | None,
        module: str | None,
        action_type: str | None,
        result: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        limit: int,
    ) -> PaginatedResult[AuditLogResponse]:
        """多條件查詢（後端分頁、時間倒序）。回 {data, meta}，data 為 AuditLogResponse。"""
        conditions = build_audit_conditions(
            operator=operator,
            module=module,
            action_type=action_type,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )
        total = await self._repo.count_logs(db, conditions=conditions)
        total_pages = (total + limit - 1) // limit if total > 0 else 0

        if total == 0 or page > total_pages:
            data: list[AuditLogResponse] = []
        else:
            rows = await self._repo.list_logs(db, conditions=conditions, offset=(page - 1) * limit, limit=limit)
            data = [self._to_response(row) for row in rows]

        return {
            "data": data,
            "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages},
        }

    async def export_csv(
        self,
        db: AsyncSession,
        *,
        operator: str | None,
        module: str | None,
        action_type: str | None,
        result: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        """依查詢條件全量匯出 CSV（無分頁）；回含 UTF-8 BOM 的字串（Excel 中文相容）。"""
        conditions = build_audit_conditions(
            operator=operator,
            module=module,
            action_type=action_type,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )
        rows = await self._repo.fetch_for_export(db, conditions=conditions)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([header for _, header in _CSV_COLUMNS])
        for row in rows:
            resp = self._to_response(row)
            writer.writerow(
                [_sanitize_csv_cell(_format_value(field, getattr(resp, field))) for field, _ in _CSV_COLUMNS]
            )
        # BOM 讓 Excel 正確辨識 UTF-8 中文
        return "﻿" + buffer.getvalue()

    @staticmethod
    def _to_response(row: Row) -> AuditLogResponse:
        """Row(DpAuditLog, operator_name) → AuditLogResponse。"""
        log, operator_name = row
        return AuditLogResponse(
            log_id=log.log_id,
            created_date=log.created_date,
            operator_id=log.created_user,
            operator_name=operator_name,
            module=log.module,
            func_name=log.func_name,
            action_type=log.action_type,
            result=log.result,
            target_id=log.target_id,
            source_ip=log.source_ip,
            description=log.description,
            before_value=log.before_value,
            after_value=log.after_value,
        )
