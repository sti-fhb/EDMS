"""簽核中心資料存取（US6，讀待簽核 / 明細 / 已完成 + 發布版本切換寫入 + 收件名單查詢）。

僅 flush 不 commit（交易由 service / middleware 負責）。跨子模組（同屬 DM）直接引用 Model。
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import Row, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.review.models import DmChangeLog, DmReview
from app.dm.roles.authz import DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

_PENDING = "PENDING"
_PUBLISHED = "PUBLISHED"
_SUPERSEDED = "SUPERSEDED"
_AUDIENCE = "AUDIENCE"
_ALL_AUDIENCE_TAG = "全體"
_COMPLETED_STATUSES = ("APPROVED", "REJECTED")


class ReviewCenterRepository:
    """簽核中心查詢 + 發布切換寫入。"""

    async def list_pending(self, db: AsyncSession, reviewer_id: str) -> list[Row]:
        """列指派給該審核者之 PENDING 送審（含文件 / 版本 / 送審者姓名），停留最久者在前。"""
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.submit_date,
                DmReview.created_user.label("submitter_id"),
                DmDocument.doc_name,
                DmDocument.category_code,
                DmDocVersion.version_no,
                DpUser.user_name.label("submitter_name"),
            )
            .join(DmDocument, DmReview.doc_id == DmDocument.doc_id)
            .outerjoin(DmDocVersion, DmReview.version_id == DmDocVersion.version_id)
            .outerjoin(DpUser, DmReview.created_user == DpUser.user_id)
            .where(DmReview.assigned_reviewer == reviewer_id, DmReview.status == _PENDING)
            .order_by(DmReview.submit_date.asc())
        )
        return list((await db.execute(stmt)).all())

    async def get_review(self, db: AsyncSession, review_id: int) -> DmReview | None:
        """取送審紀錄（供核准 / 退回之狀態轉移）。"""
        return await db.scalar(select(DmReview).where(DmReview.review_id == review_id))

    async def get_detail_row(self, db: AsyncSession, review_id: int) -> Row | None:
        """取明細 enriched 列（review + 文件 + 送審版本 meta + 送審者姓名）。"""
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.submit_date,
                DmReview.created_user.label("submitter_id"),
                DmDocument.doc_name,
                DmDocument.category_code,
                DmDocument.current_version_id,
                DmDocVersion.version_id.label("new_version_id"),
                DmDocVersion.version_no.label("new_version_no"),
                DmDocVersion.change_summary,
                DmDocVersion.file_name.label("new_file_name"),
                DmDocVersion.file_size.label("new_file_size"),
                DmDocVersion.file_mime.label("new_file_mime"),
                DpUser.user_name.label("submitter_name"),
            )
            .join(DmDocument, DmReview.doc_id == DmDocument.doc_id)
            .outerjoin(DmDocVersion, DmReview.version_id == DmDocVersion.version_id)
            .outerjoin(DpUser, DmReview.created_user == DpUser.user_id)
            .where(DmReview.review_id == review_id)
        )
        return (await db.execute(stmt)).first()

    async def get_version_meta(self, db: AsyncSession, version_id: int) -> Row | None:
        """取某版本之檔案 meta（明細比對用）。"""
        return (
            await db.execute(
                select(
                    DmDocVersion.version_id,
                    DmDocVersion.version_no,
                    DmDocVersion.file_name,
                    DmDocVersion.file_size,
                    DmDocVersion.file_mime,
                ).where(DmDocVersion.version_id == version_id)
            )
        ).first()

    async def count_completed(self, db: AsyncSession, reviewer_id: str) -> int:
        """該審核者已完成（核准 / 退回）之總數。"""
        return await db.scalar(
            select(func.count())
            .select_from(DmReview)
            .where(DmReview.approver_user_id == reviewer_id, DmReview.status.in_(_COMPLETED_STATUSES))
        )

    async def list_completed(self, db: AsyncSession, reviewer_id: str, *, offset: int, limit: int) -> list[Row]:
        """該審核者已完成清單（完成時間 DESC、後端分頁）。"""
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.status,
                DmReview.complete_date,
                DmDocument.doc_name,
                DmDocVersion.version_no,
            )
            .join(DmDocument, DmReview.doc_id == DmDocument.doc_id)
            .outerjoin(DmDocVersion, DmReview.version_id == DmDocVersion.version_id)
            .where(DmReview.approver_user_id == reviewer_id, DmReview.status.in_(_COMPLETED_STATUSES))
            .order_by(DmReview.complete_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await db.execute(stmt)).all())

    async def get_document(self, db: AsyncSession, doc_id: str) -> DmDocument | None:
        return await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id, DmDocument.deleted == 0))

    async def get_version(self, db: AsyncSession, version_id: int) -> DmDocVersion | None:
        return await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == version_id))

    async def write_change_log(
        self, db: AsyncSession, *, doc_id: str, version_id: int, operation: str, applicant: str, approver: str
    ) -> None:
        """寫入公開變更歷程（append-only、發布 / 廢止事件）。"""
        now = utcnow()
        db.add(
            DmChangeLog(
                doc_id=doc_id,
                version_id=version_id,
                operation=operation,
                applicant_user_id=applicant,
                approver_user_id=approver,
                operation_time=now,
                created_user=approver,
                created_date=now,
            )
        )
        await db.flush()

    async def get_user_name_email(self, db: AsyncSession, user_id: str) -> Row | None:
        return (
            await db.execute(
                select(DpUser.user_name, DpUser.email).where(DpUser.user_id == user_id, DpUser.deleted == 0)
            )
        ).first()

    async def recipient_emails(self, db: AsyncSession, doc_id: str, author_id: str) -> list[str]:
        """發布通知收件名單（FR-008）：撰寫者 + 具閱覽者角色且可見對象相符（或文件掛「全體」）之使用者 Email。

        反向於 `visibility.visible_docs_condition`（該函式為「使用者能看哪些文件」）：此處為「此文件能被誰看見」。
        發布當下組出快照、不追溯後續授權；不排除兼具編輯 / 審核者；Email 去重。
        """
        doc_has_all = await db.scalar(
            select(
                exists(
                    select(1)
                    .select_from(DmDocTag)
                    .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
                    .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
                    .where(
                        DmDocTag.doc_id == doc_id,
                        DmDocTag.deleted == 0,
                        DmTagGroup.group_type == _AUDIENCE,
                        DmTag.tag_name == _ALL_AUDIENCE_TAG,
                    )
                )
            )
        )
        # 文件之可見對象 AUDIENCE 標籤集（有效）
        doc_audience_tags = (
            select(DmDocTag.tag_id)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0, DmTagGroup.group_type == _AUDIENCE)
        )
        viewer_match = exists(
            select(1)
            .select_from(DmUserTag)
            .where(
                DmUserTag.user_id == DpUser.user_id,
                DmUserTag.deleted == 0,
                DmUserTag.tag_id.in_(doc_audience_tags),
            )
        )
        stmt = (
            select(DpUser.email)
            .join(DmUserRole, and_(DmUserRole.user_id == DpUser.user_id, DmUserRole.role_code == DM_VIEWER))
            .where(DpUser.deleted == 0, DmUserRole.deleted == 0, DpUser.email.isnot(None))
        )
        if not doc_has_all:
            stmt = stmt.where(or_(viewer_match, DpUser.user_id == author_id))
        emails = {e for e in (await db.scalars(stmt)).all() if e}
        # 撰寫者一定收（可能非閱覽者角色）
        author_email = await db.scalar(select(DpUser.email).where(DpUser.user_id == author_id, DpUser.deleted == 0))
        if author_email:
            emails.add(author_email)
        return sorted(emails)

    async def list_overdue_pending(self, db: AsyncSession, threshold_days: int) -> list[Row]:
        """催辦掃描：停留 ≥ 門檻天數之 PENDING（含審核者 Email、文件名），供每日批次。"""
        cutoff: datetime = utcnow() - timedelta(days=threshold_days)
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.assigned_reviewer,
                DmReview.submit_date,
                DmDocument.doc_name,
                DpUser.email.label("reviewer_email"),
                DpUser.user_name.label("reviewer_name"),
            )
            .join(DmDocument, DmReview.doc_id == DmDocument.doc_id)
            .outerjoin(DpUser, DmReview.assigned_reviewer == DpUser.user_id)
            .where(DmReview.status == _PENDING, DmReview.submit_date <= cutoff)
        )
        return list((await db.execute(stmt)).all())

    @staticmethod
    def waiting_days(submit_date: datetime) -> int:
        """送審至今之停留天數（無條件捨去）。"""
        return max(0, (utcnow() - submit_date).days)

    @staticmethod
    def released_condition() -> Sequence[str]:
        return (_PUBLISHED, _SUPERSEDED)
