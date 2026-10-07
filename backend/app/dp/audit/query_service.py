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
from app.core.utils import format_taipei
from app.dp.audit.repository import AuditLogRepository, build_audit_conditions
from app.dp.audit.schemas import AuditLogResponse, AuditOptionItem
from app.dp.audit.target_resolver import resolve_target_displays

# func_name → 中文顯示名（保留模組前綴，UI 不另列模組欄）；未知碼原樣回傳。
#
# **本表是功能碼的單一事實來源**：同時決定「功能」查詢下拉（經 /options 端點送給前端）、
# 列表的功能欄中文、CSV 匯出的功能欄中文。各模組新增稽核寫入點時於此登記即可，前端會自動出現。
#
# ⚠️ 漏登記的後果是靜默的（`_func_label()` 查不到就回原碼、下拉少一個選項，都不報錯），
# 故由 `tests/unit/dp/test_dp_audit_func_labels.py` 掃 `app/` 下所有 func_name 字面值守門。
_FUNC_LABELS: dict[str, str] = {
    "DP-USERS": "DP-使用者管理",
    "DP-PARAMS": "DP-系統參數",
    "DP-TEMPLATES": "DP-通知範本",
    "DP-PROFILE": "DP-個人資料",
    "DP-FORGOT": "DP-忘記密碼",
    "DP-REGISTER": "DP-自助註冊",
    "DP-AUTH": "DP-登入登出",
    "DP-SCHEDULE": "DP-排程管理",
    "DM-ROLES": "DM-角色/權限",
    "DM-CATALOG": "DM-受控清單",
    # DM（#477 補）：spec 僅定義 DM-ROLES / DM-CATALOG，以下四碼依寫入端語意命名
    "DM-EDITOR": "DM-文件編輯",  # create_document / add_version / update_draft_version
    "DM-REVIEW": "DM-簽核",  # approve / reject / 廢止核准
    "DM-OBSOLETE": "DM-廢止申請",  # initiate
    "DM-PERSONAL": "DM-個人專區",  # delete_draft / withdraw
    # ET（#477 補）：名稱取自 docs/specs/et/spec.md §稽核來源功能碼之「涵蓋動作」，非自行發明
    "ET-ROLES": "ET-角色/標籤指派",
    "ET-CATALOG": "ET-受控清單",
    "ET-COURSE": "ET-課程維護",
    "ET-ENROLLMENT": "ET-學員異動",
    "ET-QUIZ-RESET": "ET-重置作答次數",
    # ⚠️ 只涵蓋「SCHET002 系統代替學員交卷」。學員自己按提交**不寫稽核**（spec 明定），
    # 故不可命名為「測驗作答」——那會讓人以為每次作答都有紀錄。
    "ET-ATTEMPT": "ET-逾期自動交卷",
    "ET-REPORT": "ET-週報匯出",
    "ET-APPROVAL": "ET-線下核可",
    "ET-EXPORT": "ET-個資匯出",
}

# 供前端「功能」查詢下拉（value=func_name、label=中文）。
FUNC_OPTIONS: list[AuditOptionItem] = [AuditOptionItem(value=c, label=label) for c, label in _FUNC_LABELS.items()]

# 對象解析失敗時，從稽核列自身 before/after JSON 撈可讀名稱之鍵（優先序）。
_TARGET_NAME_KEYS = ("user_name", "template_name", "param_name", "name", "email")

# 操作類別 / 執行結果 → 中文（CSV 匯出與畫面共用）；API 收發一律維持英文碼。未知碼原樣輸出。
# 前端經 /options 端點取得，不再自行維護一份（#477 取消雙寫）。
# ⚠️ 新增 action_type 時，router 的 `_Action` 值域與 `DP_PARAM.ACTION_TYPE` 種子也要補，
# 否則該值會「選得到但查不了」（422）——#322 的 EXPORT 就是只補了這裡而漏掉那兩處。
_ACTION_LABELS: dict[str, str] = {
    "LOGIN": "登入",
    "LOGOUT": "登出",
    "CREATE": "新增",
    "UPDATE": "修改",
    "DELETE": "刪除",
    # ET02 具名個資匯出（#322 / SA 裁示 2026-09-14）
    "EXPORT": "匯出",
    # 不指名條件之大量讀取（#548 裁示 5：ET04 核可查詢未給關鍵字時）
    "QUERY": "查詢",
}
_RESULT_LABELS: dict[str, str] = {"SUCCESS": "成功", "FAIL": "失敗"}
_MODULE_LABELS: dict[str, str] = {"DP": "平台", "ET": "教育訓練", "DM": "文件管理"}

# 供前端「操作類別」/「執行結果」/「模組」查詢下拉。與 FUNC_OPTIONS 一同由 /options 端點送出，
# 前端不再自行維護清單——#477 之前前端 auditLabels.ts 與此處各有一份，靠註解要求「手動同步」，
# 結果兩邊同步了但同步的是同一份過時清單。
ACTION_OPTIONS: list[AuditOptionItem] = [AuditOptionItem(value=c, label=label) for c, label in _ACTION_LABELS.items()]
RESULT_OPTIONS: list[AuditOptionItem] = [AuditOptionItem(value=c, label=label) for c, label in _RESULT_LABELS.items()]
MODULE_OPTIONS: list[AuditOptionItem] = [AuditOptionItem(value=c, label=label) for c, label in _MODULE_LABELS.items()]

# CSV 欄位 → 中文對照表（_csv_cell 依此決定是否轉換）。
_CSV_CODE_LABELS: dict[str, dict[str, str]] = {"action_type": _ACTION_LABELS, "result": _RESULT_LABELS}


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
    # 標頭標明時區（#519）：這份檔案是調查證據，而 2026-10-05 之前匯出的版本內容是 UTC、
    # 之後是台灣時間，兩份檔案長得一模一樣。沒有標示的話，日後把新舊匯出並排比對的人
    # 會看到「同一筆 LOG 的時間被改過」卻找不到任何線索。
    ("created_date", "操作時間（台灣時間 UTC+8）"),
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
    """欄位值 → CSV 字串（操作時間以**台灣時間**格式化至秒；None → 空字串）。

    ⚠️ 原本直接 `strftime`，取到的是 UTC 牆上時間（asyncpg 解碼 `timestamptz` 回的恆為
    UTC aware），而同一頁的畫面列表走瀏覽器本地時間（台灣）——**同一筆事件，畫面與匯出檔
    差 8 小時**。這份 CSV 是稽核調查用的證據，不該有這種歧義（#519）。

    同一次（#519）把 `repository.build_audit_conditions` 的日期篩選也改成台灣日界，
    故**篩選、畫面、匯出三者現在同一基準**。
    ⚠️ 先前的版本曾把這裡的理由寫成「日期篩選已於 #483 改以台灣時間切日」——那是錯的：
    #483 改的是 `func.date()` 的 session timezone，只對 DM 那三支生效，DP 稽核當時仍自組
    UTC 午夜邊界。若日後有人要再動時區，請直接讀 `repository.py`，不要相信這類轉述。

    秒不可省：同一分鐘內的多筆事件若降精度到分，先後順序就消失了。
    """
    if value is None:
        return ""
    if field == "created_date" and isinstance(value, datetime):
        return format_taipei(value, with_seconds=True)
    return str(value)


def _sanitize_csv_cell(text: str) -> str:
    """CSV formula injection 防護：以危險字元開頭者前置單引號，令試算表視為文字。"""
    if text and text[0] in _CSV_INJECTION_PREFIXES:
        return "'" + text
    return text


def _csv_cell(resp: AuditLogResponse, field: str) -> str:
    """取 CSV 欄位值並套注入防護（操作者帳號取 email、退 operator_id；代碼欄轉中文）。"""
    if field == "operator_account":
        value: object = resp.operator_email or resp.operator_id
    else:
        value = getattr(resp, field)
    labels = _CSV_CODE_LABELS.get(field)
    if labels is not None and isinstance(value, str):
        value = labels.get(value, value)
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
