"""系統儀表板（US7 / DM00）資料存取——統計計數 + 近 30 天公告（唯讀查詢）。

跨子模組（同屬 DM）直接引用 Model；純讀取、不寫入。
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dm.catalog.models import DmCategory
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.document.visibility import visible_docs_condition
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_APPROVED = "APPROVED"
_ANNOUNCE_KINDS = ("NEW", "NEW_VERSION")
# 在架（對外有效）＝已發布 + 廢止待簽核；OBSOLETE（已下架）/ 送審 / 草稿 / SUPERSEDED（舊版）不計。
_LIVE_STATUSES = (_PUBLISHED, _PENDING_OBSOLETE)


class DashboardRepository:
    """儀表板統計 / 公告查詢。"""

    async def builtin_categories(self, db: AsyncSession) -> list[Row]:
        """內建分類（code + name）；名稱可能經 US1 改名，故自 DB 取。"""
        stmt = select(DmCategory.category_code, DmCategory.category_name).where(DmCategory.is_builtin.is_(True))
        return list((await db.execute(stmt)).all())

    async def published_counts_by_category(
        self, db: AsyncSession, *, user_id: str, roles: Iterable[str]
    ) -> dict[str, int]:
        """各分類「已發布目前版本」文件數（在架文件；含 PENDING_OBSOLETE、排除 OBSOLETE/送審/草稿）。

        套標籤式可見性（閱覽者只計其可見範圍；privileged 回 None 不過濾）——與 library 計數口徑一致，
        不洩漏受限可見對象文件之存在（Sec MEDIUM-1）。
        """
        conds = [
            DmDocument.deleted == 0,
            DmDocument.status.in_(_LIVE_STATUSES),
            DmDocument.current_version_id.is_not(None),
        ]
        visibility = visible_docs_condition(user_id, roles)
        if visibility is not None:
            conds.append(visibility)
        stmt = select(DmDocument.category_code, func.count()).where(*conds).group_by(DmDocument.category_code)
        return {row[0]: row[1] for row in (await db.execute(stmt)).all()}

    async def recent_announcements(
        self, db: AsyncSession, *, cutoff: datetime, limit: int, user_id: str, roles: Iterable[str]
    ) -> list[Row]:
        """近 cutoff 起之已發布版本（含新增/新版本 badge）——發布時間 DESC + doc_id 次要鍵。

        - 套標籤式可見性（閱覽者只見其可見範圍；privileged 不過濾）——不洩漏受限文件之標題/摘要/作者（Sec HIGH-1）。
        - 另限文件在架（`_LIVE_STATUSES`）——US8 廢止上線後不誤列剛廢止文件（Code MED）。
        - badge join 限 APPROVED 之 NEW/NEW_VERSION——避免 US8 之 OBSOLETE review 同 version_id 產生重複列（Code MED）；
          種子 / 無對應 review → None，由 service 預設為 NEW。撰寫者取版本 `CREATED_USER`（對齊「作者跟版本」）。
        """
        author = aliased(DpUser)
        review = aliased(DmReview)
        conds = [
            DmDocument.deleted == 0,
            DmDocument.status.in_(_LIVE_STATUSES),
            DmDocVersion.status == _PUBLISHED,
            DmDocVersion.published_date >= cutoff,
        ]
        visibility = visible_docs_condition(user_id, roles)
        if visibility is not None:
            conds.append(visibility)
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
            .outerjoin(
                review,
                (review.version_id == DmDocVersion.version_id)
                & (review.status == _APPROVED)
                & (review.review_type.in_(_ANNOUNCE_KINDS)),
            )
            .where(*conds)
            .order_by(DmDocVersion.published_date.desc(), DmDocVersion.doc_id)
            .limit(limit)
        )
        return list((await db.execute(stmt)).all())
