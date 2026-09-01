"""文件變更歷程查詢服務（US11，唯讀）。

DM_ADMIN-only（FR-001）：清單 / 匯出前先過 `_ensure_admin`（後端硬閘擋直連）。清單依 obsolete_archive /
library 手動分頁範式（enriched 多來源列，`paginate()` scalars 不適用）。CSV 重用 `core/csv_export` 公式注入防護。
"""

import csv
import io
from collections.abc import Iterable, Sequence

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csv_export import sanitize_csv_cell
from app.core.exceptions import AppError
from app.core.pagination import PaginatedResult
from app.dm.change_log.repository import ChangeLogRepository
from app.dm.change_log.schemas import ChangeLogEntry, ChangeLogQuery
from app.dm.roles.authz import DM_ADMIN, has_role

_CSV_HEADERS = ["時間", "申請人", "核准人", "操作", "文件編號", "文件名稱", "版本號", "備註"]
_OP_LABEL = {"PUBLISH": "發布", "OBSOLETE": "廢止"}


class ChangeLogService:
    """公開變更歷程查詢（清單 / CSV 匯出）。"""

    def __init__(self, repository: ChangeLogRepository | None = None) -> None:
        self._repo = repository or ChangeLogRepository()

    @staticmethod
    def _ensure_admin(roles: Iterable[str]) -> None:
        """FR-001 後端硬閘：非 DM_ADMIN 一律 403（對應 DM-MSG-DM08-002）。"""
        if not has_role(roles, DM_ADMIN):
            raise AppError(status_code=403, detail="需要文件管理者權限", error_code="DM_AUTH_003")

    async def search(
        self, db: AsyncSession, *, query: ChangeLogQuery, roles: Iterable[str], page: int, limit: int
    ) -> PaginatedResult[ChangeLogEntry]:
        """多條件查詢變更歷程（後端分頁、時間 DESC）。"""
        self._ensure_admin(roles)
        stmt = self._repo.enriched_select(
            keyword=query.keyword, operation=query.operation, date_from=query.date_from, date_to=query.date_to
        )
        total = await self._repo.count(db, stmt)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        if total == 0 or page > total_pages:
            return {"data": [], "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}
        rows = await self._repo.list_page(db, stmt, offset=(page - 1) * limit, limit=limit)
        data = [self._to_entry(r) for r in rows]
        return {"data": data, "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

    async def export_csv(self, db: AsyncSession, *, query: ChangeLogQuery, roles: Iterable[str]) -> bytes:
        """匯出當前查詢結果為 CSV（FR-004，全量、無分頁）。含 UTF-8 BOM 供 Excel 正確辨識中文。"""
        self._ensure_admin(roles)
        stmt = self._repo.enriched_select(
            keyword=query.keyword, operation=query.operation, date_from=query.date_from, date_to=query.date_to
        )
        rows = await self._repo.list_all(db, stmt)
        buf = io.StringIO()
        writer = csv.writer(buf)  # csv 模組處理逗號 / 換行 / 引號跳脫，禁手拼
        writer.writerow(_CSV_HEADERS)
        for r in rows:
            writer.writerow(self._to_csv_row(r))
        return buf.getvalue().encode("utf-8-sig")

    @staticmethod
    def _to_entry(r: Row) -> ChangeLogEntry:
        return ChangeLogEntry(
            change_log_id=r.change_log_id,
            operation_time=r.operation_time,
            operation=r.operation,
            applicant_id=r.applicant_id,
            applicant_name=r.applicant_name,
            approver_id=r.approver_id,
            approver_name=r.approver_name,
            doc_id=r.doc_id,
            doc_name=r.doc_name,
            version_no=r.version_no,
            note=r.note,
        )

    @staticmethod
    def _to_csv_row(r: Row) -> Sequence[str]:
        op_at = r.operation_time.strftime("%Y-%m-%d %H:%M") if r.operation_time else ""
        # 含使用者自由輸入欄位（姓名 / 文件名 / 版號 / 備註）→ 一律過公式注入防護（CWE-1236）
        return [
            op_at,
            sanitize_csv_cell(r.applicant_name or r.applicant_id or ""),
            sanitize_csv_cell(r.approver_name or r.approver_id or ""),
            _OP_LABEL.get(r.operation, r.operation),
            sanitize_csv_cell(r.doc_id),
            sanitize_csv_cell(r.doc_name),
            sanitize_csv_cell(r.version_no or ""),
            sanitize_csv_cell(r.note or ""),
        ]
