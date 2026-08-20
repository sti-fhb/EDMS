"""簽核中心服務（US6 / DM04，寫入編排）。

重用 Foundation `ReviewService.approve/reject`（狀態機核心）並編排發布 / 退回之連帶效果：

- **核准並發布**（NEW / NEW_VERSION）：核准 → 版本切換（新版 PUBLISHED、舊發布版 SUPERSEDED、
  DM_DOCUMENT.CURRENT_VERSION_ID 指新版）→ 寫 DM_CHANGE_LOG(PUBLISH) → 組收件名單 → DOC_PUBLISH 通知。
- **退回**：核准機關填原因 → 送審版本回 DRAFT（供撰寫者續編再送或刪除，FR-004）；首版（NEW）文件亦回
  DRAFT，已發布文件之新版（NEW_VERSION）**文件維持 PUBLISHED**（SA 裁示 Q2：不影響現有已發布版本）→
  DOC_REJECT 通知撰寫者。

OBSOLETE 核准與撤回消失情境屬 US8 / US9，本服務以 DM_REVIEW_006 擋 OBSOLETE。交易由 get_db 於請求
結束統一 commit；本層僅 flush，故核准 + 版本切換 + 變更歷程 + 通知同一交易原子成立。
"""

from dataclasses import dataclass

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.pagination import PaginatedResult
from app.core.utils import utcnow
from app.dm.document.file_store import is_previewable
from app.dm.notify.service import DmNotifier
from app.dm.review.repository import ReviewCenterRepository
from app.dm.review.schemas import (
    ApproveResult,
    CompletedItem,
    PendingItem,
    RejectResult,
    ReviewDetail,
    VersionMeta,
)
from app.dm.review.service import ReviewService
from app.services import AuditLogService

_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"
_OBSOLETE = "OBSOLETE"
_DRAFT = "DRAFT"
_PUBLISHED = "PUBLISHED"
_SUPERSEDED = "SUPERSEDED"
_REJECTED = "REJECTED"

_NOT_FOUND = AppError(status_code=404, detail="查無此送審項目或無權存取", error_code="DM_DOC_001")


@dataclass(slots=True)
class ReviewFile:
    """簽核明細待審 / 比對檔案之落地資訊（供 router 組 FileResponse）。"""

    path: str
    mime: str
    name: str


class ReviewCenterService:
    """簽核中心：待簽核 / 明細 / 核准並發布 / 退回 / 已完成 / 催辦掃描。"""

    def __init__(
        self,
        repository: ReviewCenterRepository | None = None,
        reviews: ReviewService | None = None,
        notifier: DmNotifier | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or ReviewCenterRepository()
        self._reviews = reviews or ReviewService()
        self._notifier = notifier or DmNotifier()
        self._audit = audit or AuditLogService()

    async def _log(self, db, *, action_type: str, operator_id: str, target: str, after: dict) -> None:
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-REVIEW",
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=target,
            after_value=after,
        )

    # ── 讀取 ──────────────────────────────────────────

    async def list_pending(self, db, *, op: OperatorInfo) -> list[PendingItem]:
        """待簽核清單（指派給自己之 PENDING、停留最久在前）。"""
        rows = await self._repo.list_pending(db, op.user_id)
        return [
            PendingItem(
                review_id=r.review_id,
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                category_code=r.category_code,
                review_type=r.review_type,
                version_no=r.version_no,
                submitter_id=r.submitter_id,
                submitter_name=r.submitter_name,
                submit_date=r.submit_date,
                waiting_days=self._repo.waiting_days(r.submit_date),
            )
            for r in rows
        ]

    async def get_detail(self, db, *, review_id: int, op: OperatorInfo) -> ReviewDetail:
        """簽核明細（僅指定審核者本人可看；新版本附目前發布版供比對）。"""
        review = await self._repo.get_review(db, review_id)
        if review is None:
            raise _NOT_FOUND
        if review.assigned_reviewer != op.user_id:
            raise AppError(status_code=403, detail="非指定審核者，不可檢視此送審", error_code="DM_REVIEW_005")
        row = await self._repo.get_detail_row(db, review_id)
        new_version = None
        if row.new_version_id is not None:
            new_version = VersionMeta(
                version_id=row.new_version_id,
                version_no=row.new_version_no,
                file_name=row.new_file_name,
                file_size=row.new_file_size,
                file_mime=row.new_file_mime,
                previewable=is_previewable(row.new_file_mime or ""),
            )
        current_version = None
        # 新版本申請：另附目前發布版（供新舊比對下載）；首版無舊版
        if review.review_type == _NEW_VERSION and row.current_version_id is not None:
            cv = await self._repo.get_version_meta(db, row.current_version_id)
            if cv is not None:
                current_version = VersionMeta(
                    version_id=cv.version_id,
                    version_no=cv.version_no,
                    file_name=cv.file_name,
                    file_size=cv.file_size,
                    file_mime=cv.file_mime,
                    previewable=is_previewable(cv.file_mime or ""),
                )
        return ReviewDetail(
            review_id=row.review_id,
            doc_id=row.doc_id,
            doc_name=row.doc_name,
            category_code=row.category_code,
            review_type=row.review_type,
            change_summary=row.change_summary,
            submit_date=row.submit_date,
            submitter_id=row.submitter_id,
            submitter_name=row.submitter_name,
            new_version=new_version,
            current_version=current_version,
        )

    async def prepare_file(self, db, *, review_id: int, version_id: int, op: OperatorInfo) -> ReviewFile:
        """簽核明細檔案下載：僅指定審核者本人，且僅限本送審之待審版或（新版本申請）目前發布版。

        US4 下載端點僅開放目前發布版（DM_DOC_002），無法取待審版；審核者須下載待審版方能審閱，故簽核中心
        另設此端點。不寫 DM_DOC_READ（審閱非正式閱讀）；以 review 綁定 version 白名單，杜絕越權取任意版本。
        """
        review = await self._repo.get_review(db, review_id)
        if review is None:
            raise _NOT_FOUND
        if review.assigned_reviewer != op.user_id:
            raise AppError(status_code=403, detail="非指定審核者，不可下載此送審檔案", error_code="DM_REVIEW_005")
        doc = await self._repo.get_document(db, review.doc_id)
        allowed = {review.version_id}
        if review.review_type == _NEW_VERSION and doc is not None and doc.current_version_id is not None:
            allowed.add(doc.current_version_id)  # 新版本申請：另允許目前發布版供新舊比對
        if version_id not in allowed:
            raise _NOT_FOUND
        version = await self._repo.get_version(db, version_id)
        if version is None or not version.file_path:
            raise _NOT_FOUND
        return ReviewFile(
            path=version.file_path,
            mime=version.file_mime or "application/octet-stream",
            name=version.file_name or "file",
        )

    async def list_completed(
        self, db, *, op: OperatorInfo, page: int, limit: int, keyword: str = ""
    ) -> PaginatedResult[CompletedItem]:
        """已完成清單（自己過往核准 / 退回、完成時間 DESC、後端分頁、選填文件名搜尋）。"""
        keyword = (keyword or "").strip()
        total = await self._repo.count_completed(db, op.user_id, keyword=keyword)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        if total == 0 or page > total_pages:
            return {"data": [], "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}
        rows = await self._repo.list_completed(db, op.user_id, offset=(page - 1) * limit, limit=limit, keyword=keyword)
        data = [
            CompletedItem(
                review_id=r.review_id,
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                review_type=r.review_type,
                status=r.status,
                version_no=r.version_no,
                complete_date=r.complete_date,
            )
            for r in rows
        ]
        return {"data": data, "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

    # ── 核准並發布 ────────────────────────────────────

    async def approve(self, db, *, review_id: int, op: OperatorInfo) -> ApproveResult:
        """核准並發布（NEW / NEW_VERSION）：原子完成版本切換 + 變更歷程 + 通知。"""
        review = await self._ensure_actionable(db, review_id, op)
        # 核准（PENDING→APPROVED；非 PENDING 由 ReviewService 擋 DM_REVIEW_003）
        await self._reviews.approve(db, review, approver=op.user_id)

        doc = await self._repo.get_document(db, review.doc_id)
        new_ver = await self._repo.get_version(db, review.version_id)
        if doc is None or new_ver is None:
            raise _NOT_FOUND
        now = utcnow()
        # 舊目前發布版 → SUPERSEDED（首版無舊版）
        if doc.current_version_id and doc.current_version_id != new_ver.version_id:
            old = await self._repo.get_version(db, doc.current_version_id)
            if old is not None:
                old.status = _SUPERSEDED
                old.updated_user, old.updated_date = op.user_id, now
        # 新版 → PUBLISHED、指標更新
        new_ver.status = _PUBLISHED
        new_ver.approver_user_id = op.user_id
        new_ver.published_date = now
        new_ver.updated_user, new_ver.updated_date = op.user_id, now
        doc.current_version_id = new_ver.version_id
        if doc.status != _PUBLISHED:  # 首版：文件轉已發布（已發布文件之新版維持 PUBLISHED）
            doc.status = _PUBLISHED
            doc.updated_user, doc.updated_date = op.user_id, now
        await db.flush()

        await self._repo.write_change_log(
            db,
            doc_id=doc.doc_id,
            version_id=new_ver.version_id,
            operation="PUBLISH",
            applicant=review.created_user,
            approver=op.user_id,
        )
        await self._log(
            db,
            action_type="UPDATE",
            operator_id=op.user_id,
            target=doc.doc_id,
            after={"review_id": review_id, "published_version_id": new_ver.version_id, "operation": "PUBLISH"},
        )
        notified = await self._notify_publish(db, doc=doc, new_ver=new_ver, author_id=review.created_user)
        return ApproveResult(published_version_id=new_ver.version_id, notified=notified)

    async def _notify_publish(self, db, *, doc, new_ver, author_id: str) -> int:
        """DOC_PUBLISH 通知撰寫者 + 可見對象相符閱覽者（發布當下快照）。"""
        recipients = await self._repo.recipient_emails(db, doc.doc_id, author_id)
        if not recipients:
            return 0
        result = await self._notifier.notify(
            db,
            template_code="DOC_PUBLISH",
            recipients=recipients,
            params={
                "doc_name": doc.doc_name,
                "version_no": new_ver.version_no or "",
                "change_summary": new_ver.change_summary or "",
            },
        )
        return result.queued_count

    # ── 退回 ──────────────────────────────────────────

    async def reject(self, db, *, review_id: int, reason: str, op: OperatorInfo) -> RejectResult:
        """退回：必填原因 → 送審版本回草稿（供撰寫者續編再送或刪除）；首版文件亦回 DRAFT。

        FR-004：新增與新版本退回一致——被退版本轉 DRAFT，出現於撰寫者個人專區草稿區（不再標 REJECTED）。
        新版本退回不影響現有已發布版本（文件維持 PUBLISHED、CURRENT_VERSION_ID 不動，Q2）；首版退回文件
        （本無發布版）回 DRAFT。退回結果（含原因）保存在 DM_REVIEW（狀態 REJECTED）。
        """
        reason = (reason or "").strip()
        if not reason:
            raise AppError(status_code=422, detail="請填寫退回原因", error_code="DM_REVIEW_004")
        review = await self._ensure_actionable(db, review_id, op)
        await self._reviews.reject(db, review, approver=op.user_id, reason=reason)

        now = utcnow()
        new_ver = await self._repo.get_version(db, review.version_id)
        if new_ver is not None:
            # 版本回草稿供續編。邊界：撰寫者若送審後又另開草稿，回草稿會撞「每人每文件一份草稿」唯一索引；
            # 此時保留 REJECTED（撰寫者以既有草稿續作，極少見），使退回動作不因索引衝突失敗。
            has_other_draft = await self._repo.author_has_other_draft(
                db, review.doc_id, review.created_user, exclude_version_id=new_ver.version_id
            )
            new_ver.status = _REJECTED if has_other_draft else _DRAFT
            new_ver.updated_user, new_ver.updated_date = op.user_id, now
        # 首版（NEW）退回 → 文件回 DRAFT；已發布文件之新版（NEW_VERSION）退回 → 文件維持 PUBLISHED（不動）
        if review.review_type == _NEW:
            doc = await self._repo.get_document(db, review.doc_id)
            if doc is not None and doc.status != _PUBLISHED:
                doc.status = _DRAFT
                doc.updated_user, doc.updated_date = op.user_id, now
        await db.flush()

        await self._log(
            db,
            action_type="UPDATE",
            operator_id=op.user_id,
            target=review.doc_id,
            after={"review_id": review_id, "operation": "REJECT"},
        )
        await self._notify_reject(db, doc_id=review.doc_id, author_id=review.created_user, reason=reason)
        return RejectResult(review_id=review_id)

    async def _notify_reject(self, db, *, doc_id: str, author_id: str, reason: str) -> None:
        """DOC_REJECT 通知撰寫者。"""
        author = await self._repo.get_user_name_email(db, author_id)
        doc = await self._repo.get_document(db, doc_id)
        if author is None or not author.email or doc is None:
            return
        await self._notifier.notify(
            db,
            template_code="DOC_REJECT",
            recipients=[author.email],
            params={"author_name": author.user_name, "doc_name": doc.doc_name, "reason": reason},
        )

    # ── 共用檢核 ──────────────────────────────────────

    async def _ensure_actionable(self, db, review_id: int, op: OperatorInfo):
        """取送審並確認可由本人處理：查無 404 / 非本人 403 / 廢止類本 issue 範圍外 409。

        以 FOR UPDATE 對 review 列上鎖（Sec M1）：序列化並發核准 / 退回，杜絕重複發布 / 通知 / 變更歷程。
        """
        review = await self._repo.get_review(db, review_id, for_update=True)
        if review is None:
            raise _NOT_FOUND
        if review.assigned_reviewer != op.user_id:
            raise AppError(status_code=403, detail="非指定審核者，不可處理此送審", error_code="DM_REVIEW_005")
        if review.review_type == _OBSOLETE:
            raise AppError(status_code=409, detail="廢止類送審之簽核暫未支援（待 US8）", error_code="DM_REVIEW_006")
        return review

    # ── 催辦（FR-006）──────────────────────────────────

    async def scan_overdue_and_remind(self, db, *, threshold_days: int) -> int:
        """催辦每日批次：停留 ≥ 門檻之 PENDING → AUTO_REMIND 通知指定審核者；回催辦筆數。"""
        rows = await self._repo.list_overdue_pending(db, threshold_days)
        count = 0
        for r in rows:
            if not r.reviewer_email:
                continue
            await self._notifier.notify(
                db,
                template_code="AUTO_REMIND",
                recipients=[r.reviewer_email],
                params={
                    "reviewer_name": r.reviewer_name or r.assigned_reviewer,
                    "doc_name": r.doc_name,
                    "waiting_days": str(self._repo.waiting_days(r.submit_date)),
                },
            )
            count += 1
        return count
