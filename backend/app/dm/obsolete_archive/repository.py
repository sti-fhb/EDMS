"""已廢止文件查詢資料存取（US10，唯讀）。

多條件過濾 STATUS=OBSOLETE 文件之核准廢止（DM_REVIEW REVIEW_TYPE=OBSOLETE & APPROVED）週期，
join 末版（目前發布版）取末版版號 / 末版作者、join DP_USER（作者 / 申請人 / 核准者姓名）。
DP_USER 之 JOIN 為唯讀查詢例外（sti-backend-boundaries §報表/查詢：僅 SELECT、不重實作他模組業務規則）。
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import ColumnElement, Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.like_escape import LIKE_ESCAPE_CHAR, contains
from app.dm.catalog.models import DmCategory
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

_OBSOLETE = "OBSOLETE"
_APPROVED = "APPROVED"


class ObsoleteArchiveRepository:
    """已廢止文件查詢（多條件 + 分頁；末版 + 核准廢止週期）。"""

    def build_conditions(
        self,
        *,
        keyword: str | None,
        category: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[ColumnElement[bool]]:
        """組搜尋條件：已廢止文件 × 其核准廢止週期；關鍵字比對文件名 / 廢止原因，日期比對核准完成時間。

        **不變量（doc_id join 不會重複列的依據）**：一份文件至多一筆 STATUS=APPROVED 的 OBSOLETE
        review——OBSOLETE 為文件終態（editor `_ensure_not_obsolete` 擋已廢止文件再送審；廢止核准後
        不再開新週期），故 `REVIEW_TYPE=OBSOLETE AND STATUS=APPROVED` 對每份 OBSOLETE 文件恰一筆
        （被退回 / 撤回之 OBSOLETE 週期為 REJECTED/WITHDRAWN，不入此條件）。此不變量由 review 狀態機
        維持；若未來新增「還原已廢止文件」等鬆動終態之功能，需同步在此加 DISTINCT / 每文件取一筆防護。
        """
        conds: list[ColumnElement[bool]] = [
            DmDocument.deleted == 0,
            DmDocument.status == _OBSOLETE,
            DmReview.review_type == _OBSOLETE,
            DmReview.status == _APPROVED,
            DmReview.deleted == 0,
        ]
        if keyword:
            pattern = contains(keyword)
            conds.append(
                or_(
                    DmDocument.doc_name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                    DmReview.reason.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                )
            )
        if category:
            conds.append(DmDocument.category_code == category)
        if date_from:
            conds.append(func.date(DmReview.complete_date) >= date_from)
        if date_to:
            conds.append(func.date(DmReview.complete_date) <= date_to)
        return conds

    async def count(self, db: AsyncSession, conditions: Sequence[ColumnElement[bool]]) -> int:
        stmt = (
            select(func.count(DmDocument.doc_id))
            .select_from(DmDocument)
            .join(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .join(DmReview, DmReview.doc_id == DmDocument.doc_id)
            .where(*conditions)
        )
        return await db.scalar(stmt) or 0

    def _enriched_select(self, conditions: Sequence[ColumnElement[bool]]):
        """已廢止文件 enriched 列：末版版號 / 末版作者 / 分類名 / 廢止脈絡（申請人 / 核准者 / 時間 / 原因）。"""
        author = aliased(DpUser)  # 末版作者
        applicant = aliased(DpUser)  # 廢止申請人（OBSOLETE 週期 CREATED_USER）
        approver = aliased(DpUser)  # 核准者
        return (
            select(
                DmDocument.doc_id,
                DmDocument.doc_name,
                DmDocVersion.version_no.label("latest_version_no"),
                DmDocument.category_code,
                DmCategory.category_name,
                DmDocVersion.created_user.label("author_id"),
                author.user_name.label("author_name"),
                DmReview.complete_date.label("obsolete_date"),
                DmReview.created_user.label("applicant_id"),
                applicant.user_name.label("applicant_name"),
                DmReview.approver_user_id.label("approver_id"),
                approver.user_name.label("approver_name"),
                DmReview.reason.label("obsolete_reason"),
            )
            .select_from(DmDocument)
            .join(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .join(DmReview, DmReview.doc_id == DmDocument.doc_id)
            .join(DmCategory, DmDocument.category_code == DmCategory.category_code)
            .outerjoin(author, DmDocVersion.created_user == author.user_id)
            .outerjoin(applicant, DmReview.created_user == applicant.user_id)
            .outerjoin(approver, DmReview.approver_user_id == approver.user_id)
            .where(*conditions)
            .order_by(DmReview.complete_date.desc(), DmDocument.doc_id)
        )

    async def list_page(
        self, db: AsyncSession, conditions: Sequence[ColumnElement[bool]], *, offset: int, limit: int
    ) -> list[Row]:
        stmt = self._enriched_select(conditions).offset(offset).limit(limit)
        return list((await db.execute(stmt)).all())

    async def list_all(self, db: AsyncSession, conditions: Sequence[ColumnElement[bool]]) -> list[Row]:
        """匯出用：相同條件、無分頁（依廢止時間新→舊）。"""
        return list((await db.execute(self._enriched_select(conditions))).all())
