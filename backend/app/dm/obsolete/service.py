"""文件廢止申請服務（US8 / UCDM05 / DM02）。

編輯者於 DM02 對「已發布」文件發起整份廢止：必填廢止原因、選填單檔附件（格式 / 大小比照文件上傳，
沿用 `file_store` 檢核 + storage-root 圍籬落盤，存 `DM_REVIEW.OBSOLETE_FILE_*`）、選指定審核者（排除本人）。
重用 `ReviewService.submit(OBSOLETE)` 建立送審週期（「一文件一 PENDING」唯一索引天然擋同時新版本送審，FR-004），
文件轉 `PENDING_OBSOLETE`（仍在架、仍對外，FR-003）並以 `OBS_SUBMIT` 通知審核者。核准 / 退回由簽核中心（US6）處理。
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.document.file_store import validate_upload
from app.dm.editor.storage import generate_file_id, save_upload
from app.dm.notify.service import DmNotifier
from app.dm.obsolete.repository import ObsoleteRepository
from app.dm.obsolete.schemas import InitiateObsoleteResult
from app.dm.review.service import ReviewService
from app.services import AuditLogService

_OBSOLETE = "OBSOLETE"
_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_NOT_FOUND = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")


class ObsoleteService:
    """文件廢止申請發起（US8）。"""

    def __init__(
        self,
        repository: ObsoleteRepository | None = None,
        reviews: ReviewService | None = None,
        notifier: DmNotifier | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or ObsoleteRepository()
        self._reviews = reviews or ReviewService()
        self._notifier = notifier or DmNotifier()
        self._audit = audit or AuditLogService()

    async def initiate(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        reason: str,
        reviewer_id: str,
        file_name: str | None,
        file_bytes: bytes | None,
        file_mime: str | None,
        op: OperatorInfo,
    ) -> InitiateObsoleteResult:
        """發起整份廢止申請。

        Args:
            doc_id: 目標文件（須為已發布）。
            reason: 廢止原因（必填）。
            reviewer_id: 指定審核者（必填、排除發起人本人）。
            file_name / file_bytes / file_mime: 選填單檔廢止附件（格式 / 大小比照文件上傳）。
            op: 發起人（廢止申請人）。

        Returns:
            InitiateObsoleteResult：建立之 review_id、文件新狀態、通知收件數。

        Raises:
            AppError: 缺原因（422 DM_DOC_014）、缺審核者（422 DM_DOC_015）、文件不存在（404 DM_DOC_001）、
                文件非已發布（409 DM_DOC_016）、審核者為本人（422 DM_REVIEW_001）、附件格式 / 大小違規
                （422 DM_FILE_001/002）、已有進行中送審（409 DM_REVIEW_002）。
        """
        reason = (reason or "").strip()
        if not reason:
            raise AppError(status_code=422, detail="請填寫廢止原因", error_code="DM_DOC_014")
        reviewer_id = (reviewer_id or "").strip()
        if not reviewer_id:
            raise AppError(status_code=422, detail="請選擇指定審核者", error_code="DM_DOC_015")
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        if doc.status != _PUBLISHED:
            raise AppError(status_code=409, detail="僅能對已發布文件發起廢止", error_code="DM_DOC_016")
        # 附件先檢核（大小 / 格式）——通過後才建 review、才落盤，避免違規附件產生孤兒檔 / review
        if file_bytes:
            await validate_upload(db, size_bytes=len(file_bytes), filename=file_name or "")
        # 建送審週期（OBSOLETE、指向當前發布版）：審核者=本人 → DM_REVIEW_001；
        # 已有進行中送審（含新版本）→ DM_REVIEW_002（一文件一 PENDING，FR-004）
        review = await self._reviews.submit(
            db,
            doc_id=doc_id,
            review_type=_OBSOLETE,
            assigned_reviewer=reviewer_id,
            author_id=op.user_id,
            version_id=doc.current_version_id,
            reason=reason,
        )
        # 落盤廢止附件並記 metadata（系統 FILE_ID 命名、storage-root 圍籬，防路徑穿越）
        if file_bytes:
            path = await asyncio.to_thread(
                save_upload, doc_id=doc_id, file_id=generate_file_id(), filename=file_name or "", data=file_bytes
            )
            review.obsolete_file_name = file_name
            review.obsolete_file_path = path
            review.obsolete_file_size = len(file_bytes)
            review.obsolete_file_mime = file_mime
        # 文件轉廢止待簽核（仍在架、仍對外，FR-003）
        now = utcnow()
        doc.status = _PENDING_OBSOLETE
        doc.updated_user, doc.updated_date = op.user_id, now
        await db.flush()

        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-OBSOLETE",
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=op.user_id,
            target_id=doc_id,
            after_value={"review_id": review.review_id, "review_type": _OBSOLETE, "doc_status": _PENDING_OBSOLETE},
        )
        notified = await self._notify_submit(db, reviewer_id=reviewer_id, author_id=op.user_id, doc_name=doc.doc_name)
        return InitiateObsoleteResult(review_id=review.review_id, doc_status=_PENDING_OBSOLETE, notified=notified)

    async def _notify_submit(self, db: AsyncSession, *, reviewer_id: str, author_id: str, doc_name: str) -> int:
        """通知指定審核者（OBS_SUBMIT）；審核者查無 Email 則略過（回 0）。"""
        reviewer = await self._repo.get_user_name_email(db, reviewer_id)
        if reviewer is None or not reviewer.email:
            return 0
        author = await self._repo.get_user_name_email(db, author_id)
        result = await self._notifier.notify(
            db,
            template_code="OBS_SUBMIT",
            recipients=[reviewer.email],
            params={
                "reviewer_name": reviewer.user_name,
                "author_name": author.user_name if author else author_id,
                "doc_name": doc_name,
            },
        )
        return result.queued_count
