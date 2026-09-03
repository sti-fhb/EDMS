"""送審週期 / 狀態機服務（T019）。

DM_REVIEW 建立 / 核准 / 退回 / 撤回；核心約束「**同一文件不可同時兩種送審**」——
以「該 DOC_ID 是否已存在 STATUS=PENDING 之 DM_REVIEW」判定（research §4）。撤回重送以新列記錄、
原列保留不改寫。指定審核者排除撰寫者本人（共用 authz）。

狀態機：PENDING → APPROVED / REJECTED / WITHDRAWN（皆為終態；撤回 / 退回後文件回草稿或已發布由呼叫端處理）。
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_REVIEWER, ensure_reviewer_not_author
from app.dm.roles.models import DmUserRole
from app.services import AccountQueryService

_PENDING = "PENDING"


class ReviewService:
    """送審週期建立與狀態轉移。"""

    def __init__(self, accounts: AccountQueryService | None = None) -> None:
        # 帳號可用性走 DP 出口（可注入 stub 供測試），不直接碰 DP_USER
        self._accounts = accounts or AccountQueryService()

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
            AppError: 審核者為撰寫者本人（422 DM_REVIEW_001）、指定審核者不可指定（422
                DM_REVIEW_008）、該文件已有進行中送審（409 DM_REVIEW_002）。

        Note:
            「同文件至多一筆 PENDING」以 DB partial unique index（UX_DM_REVIEW_ONE_PENDING）保證。
            先以 count 給友善錯誤，再以 IntegrityError 為並發後盾（兩個並發 submit 只會有一筆成功）。

            本方法為新增 / 新版本（editor）與廢止（obsolete）兩條送簽路徑的共同匯流點，
            故「審核者可指定性」檢核置於此處一次覆蓋兩者。
        """
        ensure_reviewer_not_author(assigned_reviewer, author_id)
        pending = await db.scalar(
            select(func.count()).select_from(DmReview).where(DmReview.doc_id == doc_id, DmReview.status == _PENDING)
        )
        if pending:
            raise AppError(
                status_code=409, detail="此文件已有進行中之送審，無法同時送出另一種送審", error_code="DM_REVIEW_002"
            )
        # 審核者可指定性置於「已有進行中送審」之後：文件層級的阻擋更切題，
        # 否則對已在送審中的文件送簽、卻先收到「審核者無效」，訊息會誤導。
        await self._ensure_assignable_reviewer(db, assigned_reviewer)
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
        try:
            async with db.begin_nested():  # SAVEPOINT：唯一索引衝突時只回退本次 INSERT，不毀呼叫方交易
                await db.flush()
        except IntegrityError as exc:
            raise AppError(
                status_code=409, detail="此文件已有進行中之送審，無法同時送出另一種送審", error_code="DM_REVIEW_002"
            ) from exc
        return review

    async def _ensure_assignable_reviewer(self, db: AsyncSession, user_id: str) -> None:
        """指定審核者須可被指定：具 `DM_REVIEWER` 且帳號未停用 / 未鎖定中（#250）。

        送簽表單的下拉已濾掉不可指定者，但那只是 UI 便利——不擋在伺服器端，直接打 API
        仍可把文件掛在一個永遠登不進系統的人身上（該送審無人可審，只能靠撰寫者撤回）；
        亦可指派給根本沒有審核者角色的人，而該人憑「自己是指定審核者」即通過
        `DM_REVIEW_005` 執行核准發布。

        兩個條件分屬不同模組、各走各的路徑（`sti-backend-boundaries`）：

        - **角色**：`DM_USER_ROLE` 為 DM 自持，直接查。
        - **帳號可用性**：`DP_USER.STATUS` 值域屬 DP 語意，且此處為**寫入前的判斷依據**，
          依邊界規則不適用「查詢類唯讀 JOIN」例外，故走 `services/__init__.py` 出口之
          `AccountQueryService`（唯讀布林）。純顯示用的下拉另以 JOIN 實作
          （`dm/roles/reviewer_query.py`），兩者判準一致由整合測試把關。

        Raises:
            AppError: 指定審核者無 DM_REVIEWER 角色或帳號不可用（422 DM_REVIEW_008）。
        """
        has_reviewer_role = await db.scalar(
            select(func.count())
            .select_from(DmUserRole)
            .where(
                DmUserRole.user_id == user_id,
                DmUserRole.role_code == DM_REVIEWER,
                DmUserRole.deleted == 0,
            )
        )
        if not has_reviewer_role or not await self._accounts.is_usable(db, user_id):
            raise AppError(
                status_code=422,
                detail="指定審核者無效或帳號已停用 / 鎖定，請重新選擇",
                error_code="DM_REVIEW_008",
            )

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
