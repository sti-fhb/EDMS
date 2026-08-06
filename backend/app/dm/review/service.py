"""送審週期 / 狀態機服務（T019）。

DM_REVIEW 建立 / 核准 / 退回 / 撤回；核心約束「**同一文件不可同時兩種送審**」——
以「該 DOC_ID 是否已存在 STATUS=PENDING 之 DM_REVIEW」判定（research §4）。撤回重送以新列記錄、
原列保留不改寫。指定審核者排除撰寫者本人（共用 authz）。

狀態機：PENDING → APPROVED / REJECTED / WITHDRAWN（皆為終態；撤回 / 退回後文件回草稿或已發布由呼叫端處理）。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.review.models import DmReview
from app.dm.roles.authz import ensure_reviewer_not_author

_PENDING = "PENDING"


class ReviewService:
    """送審週期建立與狀態轉移。"""

    async def submit(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        review_type: str,
        assigned_reviewer: str,
        author_id: str,
        version_id: int | None = None,
        reason: str | None = None,
    ) -> DmReview:
        """送出一次送審週期。

        Raises:
            AppError: 審核者為撰寫者本人（422 DM_REVIEW_001）、該文件已有進行中送審（409 DM_REVIEW_002）。
        """
        ensure_reviewer_not_author(assigned_reviewer, author_id)
        pending = await db.scalar(
            select(func.count()).select_from(DmReview).where(DmReview.doc_id == doc_id, DmReview.status == _PENDING)
        )
        if pending:
            raise AppError(
                status_code=409, detail="此文件已有進行中之送審，無法同時送出另一種送審", error_code="DM_REVIEW_002"
            )
        review = DmReview(
            doc_id=doc_id,
            version_id=version_id,
            review_type=review_type,
            assigned_reviewer=assigned_reviewer,
            status=_PENDING,
            submit_date=utcnow(),
            reason=reason,
            created_user=author_id,
            created_date=utcnow(),
        )
        db.add(review)
        await db.flush()
        return review

    async def _complete(
        self, db: AsyncSession, review: DmReview, *, status: str, approver: str, reason: str | None
    ) -> DmReview:
        """PENDING → 終態；非 PENDING 拒絕（409 DM_REVIEW_003）。"""
        if review.status != _PENDING:
            raise AppError(status_code=409, detail="此送審已非待審核狀態，無法處理", error_code="DM_REVIEW_003")
        review.status = status
        review.approver_user_id = approver
        review.complete_date = utcnow()
        if reason is not None:
            review.reason = reason
        review.updated_user = approver
        review.updated_date = utcnow()
        await db.flush()
        return review

    async def approve(self, db: AsyncSession, review: DmReview, *, approver: str) -> DmReview:
        """核准（PENDING → APPROVED）。"""
        return await self._complete(db, review, status="APPROVED", approver=approver, reason=None)

    async def reject(self, db: AsyncSession, review: DmReview, *, approver: str, reason: str) -> DmReview:
        """退回（PENDING → REJECTED），必填退回原因。"""
        return await self._complete(db, review, status="REJECTED", approver=approver, reason=reason)

    async def withdraw(self, db: AsyncSession, review: DmReview, *, operator: str) -> DmReview:
        """撤回（PENDING → WITHDRAWN），由撰寫者主動撤回。"""
        return await self._complete(db, review, status="WITHDRAWN", approver=operator, reason=None)
