"""稽核查詢 / 匯出服務（US10 / dp-audit，唯讀）。

與寫入服務（AuditLogService / SRVDP003）刻意分離：本服務僅 SELECT，不提供任何刪改。
稽核為**共用項**——不做 MODULE 過濾，`module` 僅為使用者選填之查詢條件（兩管理者皆查全部）。
operator / target 皆解析為可讀名稱（姓名 / email / 中文），使用者不看原始 ID（見 target_resolver）。
"""

import csv
import io
import json
from datetime import date, datetime

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResult
from app.dp.audit.repository import AuditLogRepository, build_audit_conditions
from app.dp.audit.schemas import AuditLogResponse
from app.dp.audit.target_resolver import resolve_target_displays

# func_name → 中文顯示名（保留模組前綴 DP-，UI 不另列模組欄）；未知碼（未來 ET-/DM-）原樣回傳。
_FUNC_LABELS: dict[str, str] = {
    "DP-USERS": "DP-使用者管理",
    "DP-PARAMS": "DP-系統參數",
    "DP-TEMPLATES": "DP-通知範本",
    "DP-PROFILE": "DP-個人資料",
    "DP-FORGOT": "DP-忘記密碼",
    "DP-REGISTER": "DP-自助註冊",
    "DP-AUTH": "DP-登入登出",
    "DP-SCHEDULE": "DP-排程管理",
}

# 供前端「功能」查詢下拉（value=func_name、label=中文）。
FUNC_OPTIONS: list[dict[str, str]] = [{"value": code, "label": label} for code, label in _FUNC_LABELS.items()]

# 對象解析失敗時，從稽核列自身 before/after JSON 撈可讀名稱之鍵（優先序）。
_TARGET_NAME_KEYS = ("user_name", "template_name", "param_name", "name", "email")


def _func_label(func_name: str) -> str:
    return _FUNC_LABELS.get(func_name, func_name)


def _display_from_values(before_value: str | None, after_value: str | None) -> str | None:
    """從稽核列 before/after JSON 撈可讀名稱（供對象已被硬刪、活表查不到時 fallback）。

    如取消邀請：pending 列已硬刪，但 before_value 留有 {"email": ...}。after 優先於 before（較貼近結果）。
    """
    for raw in (after_value, before_value):
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            for key in _TARGET_NAME_KEYS:
                value = data.get(key)
                if value:
                    return str(value)
    return None


# CSV 欄位（欄位名 → 標頭）：操作時間 / 操作者帳號(email) / 功能 / 操作類別 / 執行結果 / 對象 / 來源 IP / 前後值。
_CSV_COLUMNS: list[tuple[str, str]] = [
    ("created_date", "操作時間"),
    ("operator_account", "操作者帳號"),
    ("func_label", "功能"),
    ("action_type", "操作類別"),
    ("result", "執行結果"),
    ("target_display", "對象"),
    ("source_ip", "來源 IP"),
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


def _csv_cell(resp: AuditLogResponse, field: str) -> str:
    """取 CSV 欄位值並套注入防護（操作者帳號取 email、退 operator_id）。"""
    if field == "operator_account":
        value: object = resp.operator_email or resp.operator_id
    else:
        value = getattr(resp, field)
    return _sanitize_csv_cell(_format_value(field, value))


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
        func_name: str | None,
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
            func_name=func_name,
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
            data = await self._build_responses(db, rows)

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
        func_name: str | None,
        action_type: str | None,
        result: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        """依查詢條件全量匯出 CSV（無分頁）；回含 UTF-8 BOM 的字串（Excel 中文相容）。"""
        conditions = build_audit_conditions(
            operator=operator,
            module=module,
            func_name=func_name,
            action_type=action_type,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )
        rows = await self._repo.fetch_for_export(db, conditions=conditions)
        responses = await self._build_responses(db, rows)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([header for _, header in _CSV_COLUMNS])
        for resp in responses:
            writer.writerow([_csv_cell(resp, field) for field, _ in _CSV_COLUMNS])
        # BOM 讓 Excel 正確辨識 UTF-8 中文
        return "﻿" + buffer.getvalue()

    async def _build_responses(self, db: AsyncSession, rows: list[Row]) -> list[AuditLogResponse]:
        """批次解析對象顯示名稱後，將 Row 轉為 AuditLogResponse。"""
        target_map = await resolve_target_displays(db, ((row[0].func_name, row[0].target_id) for row in rows))
        return [self._to_response(row, target_map) for row in rows]

    @staticmethod
    def _to_response(row: Row, target_map: dict[tuple[str, str], str]) -> AuditLogResponse:
        """Row(DpAuditLog, operator_name, operator_email) → AuditLogResponse（含 func_label / target_display）。"""
        log, operator_name, operator_email = row
        target_display = None
        if log.target_id:
            # 活表解析 → 稽核列自身 JSON（對象已硬刪時仍留痕，如取消邀請）→ 原 target_id
            target_display = (
                target_map.get((log.func_name, log.target_id))
                or _display_from_values(log.before_value, log.after_value)
                or log.target_id
            )
        return AuditLogResponse(
            log_id=log.log_id,
            created_date=log.created_date,
            operator_id=log.created_user,
            operator_name=operator_name,
            operator_email=operator_email,
            module=log.module,
            func_name=log.func_name,
            func_label=_func_label(log.func_name),
            action_type=log.action_type,
            result=log.result,
            target_id=log.target_id,
            target_display=target_display,
            source_ip=log.source_ip,
            description=log.description,
            before_value=log.before_value,
            after_value=log.after_value,
        )
