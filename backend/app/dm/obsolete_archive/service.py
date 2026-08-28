"""已廢止文件查詢服務（US10，唯讀）。

DM_ADMIN-only（FR-001）：清單 / 匯出前先過 `_ensure_admin`（後端硬閘擋直連，非僅前端隱藏）；
`access` 供前端側欄逐項閘（回布林、非 403）。清單依 library 手動分頁範式（enriched 多來源列）。
"""

import csv
import io
from collections.abc import Iterable, Sequence

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.pagination import PaginatedResult
from app.dm.obsolete_archive.repository import ObsoleteArchiveRepository
from app.dm.obsolete_archive.schemas import ObsoleteAccess, ObsoleteDocItem, ObsoleteQuery
from app.dm.roles.authz import DM_ADMIN, has_role

# CSV 表頭（欄位對齊清單 FR-003）；廢止時間以 UTC 呈現供稽核封存。
_CSV_HEADERS = ["文件編號", "文件名稱", "末版版號", "分類", "原作者", "廢止時間", "廢止申請人", "核准者", "廢止原因"]


class ObsoleteArchiveService:
    """已廢止文件查詢（清單 / CSV 匯出 / 入口可見性判定）。"""

    def __init__(self, repository: ObsoleteArchiveRepository | None = None) -> None:
        self._repo = repository or ObsoleteArchiveRepository()

    @staticmethod
    def _ensure_admin(roles: Iterable[str]) -> None:
        """FR-001 後端硬閘：非 DM_ADMIN 一律 403（對應 DM-MSG-DM06-002）。"""
        if not has_role(roles, DM_ADMIN):
            raise AppError(status_code=403, detail="需要文件管理者權限", error_code="DM_AUTH_003")

    def get_access(self, roles: Iterable[str]) -> ObsoleteAccess:
        """入口可見性（供前端側欄逐項閘；鏡像 US9 個人專區 access）。"""
        return ObsoleteAccess(can_access=has_role(roles, DM_ADMIN))

    async def search(
        self, db: AsyncSession, *, query: ObsoleteQuery, roles: Iterable[str], page: int, limit: int
    ) -> PaginatedResult[ObsoleteDocItem]:
        """多條件查詢已廢止文件（後端分頁、廢止時間 DESC）。"""
        self._ensure_admin(roles)
        conditions = self._repo.build_conditions(
            keyword=query.keyword, category=query.category, date_from=query.date_from, date_to=query.date_to
        )
        total = await self._repo.count(db, conditions)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        if total == 0 or page > total_pages:
            return {"data": [], "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}
        rows = await self._repo.list_page(db, conditions, offset=(page - 1) * limit, limit=limit)
        data = [self._to_item(r) for r in rows]
        return {"data": data, "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

    async def export_csv(self, db: AsyncSession, *, query: ObsoleteQuery, roles: Iterable[str]) -> bytes:
        """匯出當前查詢結果為 CSV（FR-005，全量、無分頁）。含 UTF-8 BOM 供 Excel 正確辨識中文。"""
        self._ensure_admin(roles)
        conditions = self._repo.build_conditions(
            keyword=query.keyword, category=query.category, date_from=query.date_from, date_to=query.date_to
        )
        rows = await self._repo.list_all(db, conditions)
        buf = io.StringIO()
        writer = csv.writer(buf)  # csv 模組處理逗號 / 換行 / 引號跳脫，禁手拼
        writer.writerow(_CSV_HEADERS)
        for r in rows:
            writer.writerow(self._to_csv_row(r))
        return buf.getvalue().encode("utf-8-sig")

    @staticmethod
    def _to_item(r: Row) -> ObsoleteDocItem:
        return ObsoleteDocItem(
            doc_id=r.doc_id,
            doc_name=r.doc_name,
            latest_version_no=r.latest_version_no,
            category_code=r.category_code,
            category_name=r.category_name,
            author_id=r.author_id,
            author_name=r.author_name,
            obsolete_date=r.obsolete_date,
            applicant_id=r.applicant_id,
            applicant_name=r.applicant_name,
            approver_id=r.approver_id,
            approver_name=r.approver_name,
            obsolete_reason=r.obsolete_reason,
        )

    @staticmethod
    def _to_csv_row(r: Row) -> Sequence[str]:
        obsolete_at = r.obsolete_date.strftime("%Y-%m-%d %H:%M") if r.obsolete_date else ""
        return [
            r.doc_id,
            r.doc_name,
            r.latest_version_no or "",
            r.category_name,
            r.author_name or r.author_id or "",
            obsolete_at,
            r.applicant_name or r.applicant_id or "",
            r.approver_name or r.approver_id or "",
            r.obsolete_reason or "",
        ]
