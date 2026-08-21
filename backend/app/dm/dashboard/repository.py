"""系統儀表板（US7 / DM00）資料存取——統計計數 + 近 30 天公告（唯讀查詢）。

跨子模組（同屬 DM）直接引用 Model；純讀取、不寫入。
"""

from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dm.catalog.models import DmCategory
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser

_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_APPROVED = "APPROVED"
# 在架（對外有效）＝已發布 + 廢止待簽核；OBSOLETE（已下架）/ 送審 / 草稿 / SUPERSEDED（舊版）不計。
_LIVE_STATUSES = (_PUBLISHED, _PENDING_OBSOLETE)


class DashboardRepository:
    """儀表板統計 / 公告查詢。"""

    async def builtin_categories(self, db: AsyncSession) -> list[Row]:
        """內建分類（code + name）；名稱可能經 US1 改名，故自 DB 取。"""
        stmt = select(DmCategory.category_code, DmCategory.category_name).where(DmCategory.is_builtin.is_(True))
        return list((await db.execute(stmt)).all())

    async def published_counts_by_category(self, db: AsyncSession) -> dict[str, int]:
        """各分類「已發布目前版本」文件數（在架文件；含 PENDING_OBSOLETE、排除 OBSOLETE/送審/草稿）。"""
        stmt = (
            select(DmDocument.category_code, func.count())
            .where(
                DmDocument.deleted == 0,
                DmDocument.status.in_(_LIVE_STATUSES),
                DmDocument.current_version_id.is_not(None),
            )
            .group_by(DmDocument.category_code)
        )
        return {row[0]: row[1] for row in (await db.execute(stmt)).all()}

    async def recent_announcements(self, db: AsyncSession, *, cutoff: datetime, limit: int) -> list[Row]:
        """近 cutoff 起之已發布版本（含新增/新版本 badge）——發布時間 DESC + doc_id 次要鍵。

        badge 由該版本之 APPROVED `DM_REVIEW.REVIEW_TYPE` 取得（LEFT JOIN；種子 / 無對應 review → None，
        由 service 預設為 NEW）。撰寫者取版本 `CREATED_USER`（對齊「作者跟版本」）。
        """
        author = aliased(DpUser)
        review = aliased(DmReview)
        stmt = (
            select(
                DmDocVersion.doc_id,
                DmDocument.doc_name,
                DmDocument.category_code,
                DmDocVersion.version_no,
                DmDocVersion.change_summary,
                DmDocVersion.published_date,
                author.user_name.label("author_name"),
                review.review_type.label("kind"),
            )
            .join(DmDocument, DmDocVersion.doc_id == DmDocument.doc_id)
            .outerjoin(author, DmDocVersion.created_user == author.user_id)
            .outerjoin(review, (review.version_id == DmDocVersion.version_id) & (review.status == _APPROVED))
            .where(
                DmDocument.deleted == 0,
                DmDocVersion.status == _PUBLISHED,
                DmDocVersion.published_date >= cutoff,
            )
            .order_by(DmDocVersion.published_date.desc(), DmDocVersion.doc_id)
            .limit(limit)
        )
        return list((await db.execute(stmt)).all())
