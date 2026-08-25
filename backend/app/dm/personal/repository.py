"""個人專區（US9）資料存取：草稿匣（三類）+ 我的文件動態（衍生查詢，無新表）。"""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview

_DRAFT = "DRAFT"


class PersonalRepository:
    """草稿匣 / 我的文件動態查詢。"""

    async def list_user_drafts(self, db: AsyncSession, user_id: str) -> list[Row]:
        """該使用者之 DRAFT 版本 + 該版本最近一次送審狀態（供三類分類）。

        DRAFT 版本只會是：從未送審 / 被退回回草稿（REJECTED）/ 已撤回回草稿（WITHDRAWN）——
        PENDING 中之版本為 PENDING_REVIEW、不在此列。以相關子查詢取最近一次 DM_REVIEW.status。
        """
        latest_status = (
            select(DmReview.status)
            .where(DmReview.version_id == DmDocVersion.version_id)
            .order_by(DmReview.submit_date.desc())
            .limit(1)
            .correlate(DmDocVersion)
            .scalar_subquery()
        )
        stmt = (
            select(
                DmDocVersion.version_id,
                DmDocVersion.doc_id,
                DmDocVersion.version_no,
                DmDocVersion.change_summary,
                DmDocVersion.updated_date,
                DmDocument.doc_name,
                DmDocument.category_code,
                latest_status.label("latest_review_status"),
            )
            .join(DmDocument, DmDocVersion.doc_id == DmDocument.doc_id)
            .where(
                DmDocVersion.created_user == user_id,
                DmDocVersion.status == _DRAFT,
                DmDocVersion.deleted == 0,
            )
            .order_by(DmDocVersion.updated_date.desc().nullslast(), DmDocVersion.version_id.desc())
        )
        return list((await db.execute(stmt)).all())

    async def get_version(self, db: AsyncSession, version_id: int) -> DmDocVersion | None:
        """取未刪除版本（草稿刪除授權 / 狀態檢核用）。"""
        return await db.scalar(
            select(DmDocVersion).where(DmDocVersion.version_id == version_id, DmDocVersion.deleted == 0)
        )

    async def _activity(self, db: AsyncSession, *, column, user_id: str, since: datetime) -> list[Row]:
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.status,
                DmReview.submit_date,
                DmReview.complete_date,
                DmDocument.doc_name,
            )
            .join(DmDocument, DmReview.doc_id == DmDocument.doc_id)
            .where(column == user_id, or_(DmReview.submit_date >= since, DmReview.complete_date >= since))
            .order_by(DmReview.submit_date.desc())
        )
        return list((await db.execute(stmt)).all())

    async def list_author_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """撰寫者視角近 30 天送審事件（created_user＝我）。"""
        return await self._activity(db, column=DmReview.created_user, user_id=user_id, since=since)

    async def list_reviewer_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """審核者視角近 30 天送審事件（assigned_reviewer＝我）。"""
        return await self._activity(db, column=DmReview.assigned_reviewer, user_id=user_id, since=since)
