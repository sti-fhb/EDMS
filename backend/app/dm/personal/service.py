"""個人專區服務（US9 / UCDM09 / DM07）。

三塊 DM 業務：草稿匣（三類 + 刪除）、撤回送審（狀態回復 + 站內訊息通知原審核者）、我的文件動態（近 30 天、
角色視角）。撤回 orchestration 重用 `ReviewService.withdraw`（僅翻 DM_REVIEW 狀態）+ `ReviewCenterRepository`
之版本 / 文件狀態回復（比照 US6 reject / US8 廢止退回）。個資維護不在本模組（平台 DP UCDP004）。
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.notify.service import DmNotifier
from app.dm.personal.repository import PersonalRepository
from app.dm.personal.schemas import ActivityItem, ActivityResponse, DraftItem, WithdrawResult
from app.dm.review.repository import ReviewCenterRepository
from app.dm.review.service import ReviewService
from app.services import AuditLogService, ParamService

_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"
_OBSOLETE = "OBSOLETE"
_DRAFT = "DRAFT"
_PUBLISHED = "PUBLISHED"
_PENDING = "PENDING"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_REJECTED = "REJECTED"
_WITHDRAWN = "WITHDRAWN"
_ACTIVITY_DAYS = 30
_REMIND_THRESHOLD_DEFAULT = 7  # DM_REMIND_THRESHOLD 預設；逾此天數之 PENDING 於審核者視角顯「催辦中」
_REVIEW_NOT_FOUND = AppError(status_code=404, detail="查無此送審項目或無權存取", error_code="DM_DOC_001")
_DRAFT_NOT_FOUND = AppError(status_code=404, detail="查無此草稿版本或無權存取", error_code="DM_DOC_001")


def _classify_draft(latest_review_status: str | None) -> str:
    """依該版本最近一次送審狀態分類草稿：無 → 未送審；REJECTED → 被退回；WITHDRAWN → 已撤回。"""
    if latest_review_status == _REJECTED:
        return "rejected"
    if latest_review_status == _WITHDRAWN:
        return "withdrawn"
    return "unsubmitted"


class PersonalService:
    """個人專區：草稿匣 / 撤回送審 / 我的文件動態。"""

    def __init__(
        self,
        repository: PersonalRepository | None = None,
        review_repo: ReviewCenterRepository | None = None,
        reviews: ReviewService | None = None,
        notifier: DmNotifier | None = None,
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or PersonalRepository()
        self._review_repo = review_repo or ReviewCenterRepository()
        self._reviews = reviews or ReviewService()
        self._notifier = notifier or DmNotifier()
        self._audit = audit or AuditLogService()
        self._params = params or ParamService()

    # ── 草稿匣 ──────────────────────────────────────────

    async def list_drafts(self, db: AsyncSession, *, user_id: str) -> list[DraftItem]:
        """該使用者草稿（三類：未送審 / 被退回 / 已撤回）。"""
        rows = await self._repo.list_user_drafts(db, user_id)
        return [
            DraftItem(
                version_id=r.version_id,
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                version_no=r.version_no,
                change_summary=r.change_summary,
                category_code=r.category_code,
                kind=_classify_draft(r.latest_review_status),
                updated_date=r.updated_date,
            )
            for r in rows
        ]

    async def delete_draft(self, db: AsyncSession, *, version_id: int, op: OperatorInfo) -> None:
        """刪除草稿（軟刪）：限本人 + 版本為 DRAFT；不影響已發布版本。

        Raises:
            AppError: 查無版本（404 DM_DOC_001）、非本人（403 DM_DRAFT_001）、非草稿版本（409 DM_DRAFT_002）。
        """
        version = await self._repo.get_version(db, version_id, for_update=True)  # 鎖列：狀態檢核與軟刪之間防 TOCTOU
        if version is None:
            raise _DRAFT_NOT_FOUND
        if version.created_user != op.user_id:
            raise AppError(status_code=403, detail="僅能刪除本人之草稿", error_code="DM_DRAFT_001")
        if version.status != _DRAFT:
            raise AppError(status_code=409, detail="僅草稿版本可刪除", error_code="DM_DRAFT_002")
        now = utcnow()
        version.deleted = 1
        version.updated_user, version.updated_date = op.user_id, now
        await db.flush()
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-PERSONAL",
            action_type="DELETE",
            result="SUCCESS",
            operator_id=op.user_id,
            target_id=version.doc_id,
            after_value={"version_id": version_id, "operation": "DELETE_DRAFT"},
        )

    # ── 撤回送審 ────────────────────────────────────────

    async def withdraw(self, db: AsyncSession, *, review_id: int, op: OperatorInfo) -> WithdrawResult:
        """撤回送審（撰寫者本人）：DM_REVIEW→WITHDRAWN + 狀態回復 + 站內訊息通知原審核者。

        狀態回復：NEW / NEW_VERSION → 送審版本回 DRAFT（首版文件亦回 DRAFT；已發布文件之新版文件維持
        PUBLISHED）；OBSOLETE → 文件回 PUBLISHED。原 ASSIGNED_REVIEWER 保留不改寫。

        Raises:
            AppError: 查無（404 DM_DOC_001）、非撰寫者本人（403 DM_REVIEW_007）、非 PENDING（409 DM_REVIEW_003）。
        """
        review = await self._review_repo.get_review(db, review_id, for_update=True)
        if review is None:
            raise _REVIEW_NOT_FOUND
        if review.created_user != op.user_id:
            raise AppError(status_code=403, detail="僅送審撰寫者本人可撤回", error_code="DM_REVIEW_007")
        # 撤回（PENDING→WITHDRAWN；非 PENDING 由 ReviewService 擋 DM_REVIEW_003）
        await self._reviews.withdraw(db, review, operator=op.user_id)

        now = utcnow()
        doc = await self._review_repo.get_document(db, review.doc_id)
        doc_status = doc.status if doc is not None else ""
        if review.review_type in (_NEW, _NEW_VERSION):
            ver = await self._review_repo.get_version(db, review.version_id)
            if ver is not None:
                # 版本回草稿供續編；若撰寫者另有草稿，保留 REJECTED 避免撞「每人每文件一份草稿」唯一索引（同 US6 退回）
                has_other = await self._review_repo.author_has_other_draft(
                    db, review.doc_id, review.created_user, exclude_version_id=ver.version_id
                )
                ver.status = _REJECTED if has_other else _DRAFT
                ver.updated_user, ver.updated_date = op.user_id, now
            if review.review_type == _NEW and doc is not None and doc.status != _PUBLISHED:
                doc.status = _DRAFT  # 首版撤回 → 文件回草稿（已發布文件之新版維持 PUBLISHED）
                doc.updated_user, doc.updated_date = op.user_id, now
                doc_status = _DRAFT
        elif review.review_type == _OBSOLETE and doc is not None and doc.status == _PENDING_OBSOLETE:
            doc.status = _PUBLISHED  # 撤回廢止 → 文件回已發布（比照 US8 廢止退回）
            doc.updated_user, doc.updated_date = op.user_id, now
            doc_status = _PUBLISHED
        await db.flush()

        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-PERSONAL",
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=op.user_id,
            target_id=review.doc_id,
            after_value={"review_id": review_id, "operation": "WITHDRAW", "review_type": review.review_type},
        )
        await self._notify_withdrawn(
            db,
            reviewer_id=review.assigned_reviewer,
            author_id=review.created_user,
            doc_name=doc.doc_name if doc is not None else review.doc_id,
        )
        return WithdrawResult(review_id=review_id, doc_status=doc_status)

    async def _notify_withdrawn(self, db: AsyncSession, *, reviewer_id: str, author_id: str, doc_name: str) -> None:
        """觸發撤回通知事件（SUBMIT_WITHDRAWN，CHANNEL=MSG，對齊 AUTO_REMIND 之 MSG 事件慣例）。

        **實質站內訊息由原審核者之「我的文件動態」（審核者視角 WITHDRAWN）呈現**——平台 `send_email` 對
        MSG 頻道回 `CHANNEL_NOT_EMAIL`、不寫 outbox（不寄 Email）。此呼叫為 forward-compat 事件觸發
        （未來若平台實作站內訊息佇列即自動生效）；params key 對齊範本佔位（reviewer_name / author_name / doc_name）。
        """
        reviewer = await self._review_repo.get_user_name_email(db, reviewer_id)
        if reviewer is None or not reviewer.email:
            return
        author = await self._review_repo.get_user_name_email(db, author_id)
        await self._notifier.notify(
            db,
            template_code="SUBMIT_WITHDRAWN",
            recipients=[reviewer.email],
            params={
                "reviewer_name": reviewer.user_name,
                "author_name": author.user_name if author else author_id,
                "doc_name": doc_name,
            },
        )

    # ── 我的文件動態 ────────────────────────────────────

    async def list_activity(self, db: AsyncSession, *, user_id: str) -> ActivityResponse:
        """近 30 天送審事件（撰寫者 / 審核者視角；兼具兩角色者兩清單皆有值）。

        PENDING 項計算停留天數 + 是否逾催辦門檻（`DM_REMIND_THRESHOLD`）——審核者視角據此顯「催辦中」（AC5）。
        """
        now = utcnow()
        since = now - timedelta(days=_ACTIVITY_DAYS)
        threshold = await self._params.get_int_param(db, "DM_REMIND_THRESHOLD", "VALUE", _REMIND_THRESHOLD_DEFAULT)
        author_rows = await self._repo.list_author_activity(db, user_id, since)
        reviewer_rows = await self._repo.list_reviewer_activity(db, user_id, since)
        return ActivityResponse(
            author=[self._to_activity(r, now=now, threshold=threshold) for r in author_rows],
            reviewer=[self._to_activity(r, now=now, threshold=threshold) for r in reviewer_rows],
        )

    @staticmethod
    def _to_activity(r, *, now, threshold: int) -> ActivityItem:
        waiting_days = max((now - r.submit_date).days, 0)
        return ActivityItem(
            review_id=r.review_id,
            doc_id=r.doc_id,
            doc_name=r.doc_name,
            review_type=r.review_type,
            status=r.status,
            submit_date=r.submit_date,
            complete_date=r.complete_date,
            waiting_days=waiting_days,
            is_overdue=r.status == _PENDING and waiting_days >= threshold,
        )
