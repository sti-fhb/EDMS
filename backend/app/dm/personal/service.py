"""個人專區服務（US9 / UCDM09 / DM07）。

三塊 DM 業務：草稿匣（三類 + 刪除）、撤回送審（狀態回復）、我的文件動態（近 30 天、角色視角）。撤回
orchestration 重用 `ReviewService.withdraw`（僅翻 DM_REVIEW 狀態）+ `ReviewCenterRepository` 之版本 /
文件狀態回復（比照 US6 reject / US8 廢止退回）。

**撤回之「站內訊息通知原審核者」**：由原審核者之「我的文件動態」（審核者視角『已撤回』）呈現——平台 MSG 頻道
不寄 Email、亦不寫 outbox（DmNotifier docstring）；故本服務不主動呼叫通知接線（避免撤回因通知範本問題而崩，
且無實質遞送效果）。`SUBMIT_WITHDRAWN` 範本已 seed 供未來站內訊息佇列使用。個資維護不在本模組（平台 DP UCDP004）。
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.personal.repository import PersonalRepository
from app.dm.personal.schemas import ActivityEvent, ActivityResponse, DraftItem, WithdrawResult
from app.dm.review.repository import ReviewCenterRepository
from app.dm.review.service import ReviewService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER, has_role
from app.services import AuditLogService, ParamService

_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"
_OBSOLETE = "OBSOLETE"
_DRAFT = "DRAFT"
_PUBLISHED = "PUBLISHED"
_PENDING = "PENDING"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_APPROVED = "APPROVED"
_REJECTED = "REJECTED"
_WITHDRAWN = "WITHDRAWN"
_TERMINAL = (_APPROVED, _REJECTED, _WITHDRAWN)  # 送審週期終態（各對應一筆 resolved 事件）
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
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or PersonalRepository()
        self._review_repo = review_repo or ReviewCenterRepository()
        self._reviews = reviews or ReviewService()
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
                doc_status=r.doc_status,
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
        # 站內訊息通知原審核者：不主動呼叫通知接線——平台 MSG 頻道不寄 Email / 不寫 outbox，且若範本未 seed
        # 會使 send_email raise（撤回不應因通知而崩）。通知以原審核者之「我的文件動態」（審核者視角『已撤回』）呈現。
        return WithdrawResult(review_id=review_id, doc_status=doc_status)

    # ── 我的文件動態 ────────────────────────────────────

    async def list_activity(self, db: AsyncSession, *, user_id: str, roles: list[str]) -> ActivityResponse:
        """近 30 天「狀態變動歷程」——**依當下角色呈現視角**：具編輯者才回撰寫者視角、具審核者才回審核者視角
        （曾具但當下已無該角色者不呈現對應視角）。

        兩視角一致展開全程：送審（submitted，@送審時間）→ 若已完成再加結果（resolved：核准 / 退回 / 撤回，
        @完成時間），時間新→舊，讓「送審 → 退回 / 發布」全程可見（撰寫者與審核者呈現一致）。
        待處理與催辦中為同一送審列（PENDING 之送審事件），僅依是否逾催辦門檻（`DM_REMIND_THRESHOLD`）切換標籤，
        時間皆以送審時間為準（AC5）；退回 / 核准 / 撤回才另加一列結果事件。
        """
        now = utcnow()
        since = now - timedelta(days=_ACTIVITY_DAYS)
        threshold = await self._params.get_int_param(db, "DM_REMIND_THRESHOLD", "VALUE", _REMIND_THRESHOLD_DEFAULT)
        author: list[ActivityEvent] = []
        reviewer: list[ActivityEvent] = []
        if has_role(roles, DM_EDITOR):
            rows = await self._repo.list_author_activity(db, user_id, since)
            author = self._build_events(rows, since=since, now=now, threshold=threshold)
        if has_role(roles, DM_REVIEWER):
            rows = await self._repo.list_reviewer_activity(db, user_id, since)
            reviewer = self._build_events(rows, since=since, now=now, threshold=threshold)
        return ActivityResponse(author=author, reviewer=reviewer)

    @staticmethod
    def _build_events(rows, *, since, now, threshold: int) -> list[ActivityEvent]:
        """把送審週期列展開為狀態變動事件，過濾近 30 天內，時間新→舊排序。

        一次送審週期：PENDING → 一列送審事件（待處理 / 催辦中 / 送審中）；已完成 → 送審列 + 結果列兩列。
        """
        events: list[ActivityEvent] = []
        for r in rows:
            overdue = r.status == _PENDING and (now - r.submit_date).days >= threshold
            if r.submit_date >= since:  # 送審 / 發起廢止事件
                events.append(
                    ActivityEvent(
                        review_id=r.review_id,
                        doc_id=r.doc_id,
                        doc_name=r.doc_name,
                        review_type=r.review_type,
                        status=r.status,
                        event_kind="submitted",
                        event_time=r.submit_date,
                        is_overdue=overdue,
                        party_name=r.party_name,
                    )
                )
            if r.status in _TERMINAL and r.complete_date is not None and r.complete_date >= since:
                events.append(  # 核准 / 退回 / 撤回結果事件
                    ActivityEvent(
                        review_id=r.review_id,
                        doc_id=r.doc_id,
                        doc_name=r.doc_name,
                        review_type=r.review_type,
                        status=r.status,
                        event_kind="resolved",
                        event_time=r.complete_date,
                        is_overdue=False,
                        party_name=r.party_name,
                    )
                )
        # 時間新→舊；同時點以 review_id 為次序穩定排序（repository 已不下 order_by，順序由此決定）
        events.sort(key=lambda e: (e.event_time, e.review_id), reverse=True)
        return events
