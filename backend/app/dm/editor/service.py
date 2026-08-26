"""文件新增與編輯服務（US5 / DM03，寫入編排）。

編排三張表寫入（DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG）與跨模組送審 / 通知：

- **新增模式**：配 DOC_ID（並發撞號重試）→ 建 DRAFT 文件 + DRAFT 首版 + 標籤。
- **編輯新版本**：既有文件加 DRAFT 版本（**單一草稿**：已有未送簽草稿則擋 DM_DOC_009；廢止待簽核擋
  DM_DOC_008）+ 文件層標籤覆寫；身份欄（名稱 / 分類 / func）不吃。
- **送簽**：送簽前檢核（可見對象 ≥1 / 版號 / MANUAL func 唯一）→ `ReviewService.submit(NEW|NEW_VERSION)`
  → 版本 / 文件 STATUS 轉 PENDING_REVIEW（已發布文件維持 PUBLISHED）→ `DmNotifier` 通知審核者。

檔案先 `validate_upload` 檢核（大小 / 副檔名）再 `save_upload` 落盤（系統 FILE_ID 命名、防路徑穿越）。
交易由 `get_db` 於請求結束統一 commit；本層僅 flush，故送審 + 狀態轉移 + 通知同一交易原子成立。
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.document.docid import next_doc_id
from app.dm.document.file_store import is_previewable, validate_upload
from app.dm.editor.repository import EditorRepository
from app.dm.editor.schemas import (
    CreateResult,
    DraftMeta,
    EditorDocTags,
    EditorOptions,
    OptionItem,
    ReviewerItem,
    SubmitResult,
    VersionResult,
)
from app.dm.editor.storage import generate_file_id, save_upload
from app.dm.notify.service import DmNotifier
from app.dm.review.service import ReviewService
from app.dm.roles.authz import ensure_reviewer_not_author
from app.services import AuditLogService

_DRAFT = "DRAFT"
_PENDING_REVIEW = "PENDING_REVIEW"
_REJECTED = "REJECTED"
_WITHDRAWN = "WITHDRAWN"
_MANUAL = "MANUAL"
_AUDIENCE = "AUDIENCE"
_RETRIEVAL = "RETRIEVAL"
_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"
_MAX_DOCID_RETRY = 3

_NOT_FOUND = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")
# 送審類型 → 通知範本人類可讀標籤（DOC_SUBMIT.review_type 變數）
_REVIEW_TYPE_LABEL = {_NEW: "首次發布審核", _NEW_VERSION: "新版本審核"}


@dataclass(frozen=True)
class _FileMeta:
    """落盤後之檔案 metadata（草稿無檔案時各欄為 None）。"""

    path: str | None
    name: str | None
    size: int | None
    mime: str | None
    previewable: bool


class EditorService:
    """文件新增 / 編輯新版本 / 送簽 / 表單受控下拉。"""

    def __init__(
        self,
        repository: EditorRepository | None = None,
        reviews: ReviewService | None = None,
        notifier: DmNotifier | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or EditorRepository()
        self._reviews = reviews or ReviewService()
        self._notifier = notifier or DmNotifier()
        self._audit = audit or AuditLogService()

    async def _log(self, db: AsyncSession, *, action_type: str, operator_id: str, target: str, after: dict) -> None:
        """寫入型操作於同交易寫 SRVDP003 稽核（MODULE=DM、FUNC=DM-EDITOR、res_id=DOC_ID）。"""
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-EDITOR",
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=target,
            after_value=after,
        )

    # ── 新增模式 ──────────────────────────────────────

    async def create_document(
        self,
        db: AsyncSession,
        *,
        doc_name: str,
        category_code: str,
        func_code: str | None,
        audience_ids: Sequence[int],
        retrieval_ids: Sequence[int],
        version_no: str,
        change_summary: str,
        file_name: str | None,
        file_bytes: bytes | None,
        file_mime: str | None,
        op: OperatorInfo,
    ) -> CreateResult:
        """新增草稿文件（配 DOC_ID + DRAFT 首版 + 標籤）。

        存草稿不卡必填（US5）：名稱 / 版號 / 摘要 / 檔案皆可空，送簽時才完整檢核。分類必填（DOC_ID 配號用）。
        """
        doc_name = (doc_name or "").strip()
        version_no = (version_no or "").strip()
        change_summary = (change_summary or "").strip()
        await self._ensure_category(db, category_code)
        func_code = await self._resolve_func(db, category_code, func_code)
        tag_ids = await self._validate_tags(db, audience_ids, retrieval_ids)

        doc = await self._create_doc_with_retry(
            db, category_code=category_code, doc_name=doc_name, func_code=func_code, op=op
        )
        fmeta = await self._store_file(
            db, doc_id=doc.doc_id, file_name=file_name, file_bytes=file_bytes, file_mime=file_mime
        )
        ver = await self._repo.add_version(
            db,
            doc_id=doc.doc_id,
            version_no=version_no,
            change_summary=change_summary,
            file_name=fmeta.name,
            file_path=fmeta.path,
            file_size=fmeta.size,
            file_mime=fmeta.mime,
            op=op,
        )
        await self._repo.set_tags(db, doc_id=doc.doc_id, tag_ids=tag_ids, op=op)
        await self._log(
            db,
            action_type="CREATE",
            operator_id=op.user_id,
            target=doc.doc_id,
            after={"doc_name": doc_name, "category_code": category_code, "version_no": version_no},
        )
        return CreateResult(doc_id=doc.doc_id, version_id=ver.version_id, previewable=fmeta.previewable)

    async def _store_file(
        self, db: AsyncSession, *, doc_id: str, file_name: str | None, file_bytes: bytes | None, file_mime: str | None
    ) -> _FileMeta:
        """有檔案 → 檢核（大小 / 副檔名）+ 落盤（卸載至 thread）並回 metadata；無檔案 → 全 None（草稿允許）。"""
        if not file_bytes:
            return _FileMeta(path=None, name=None, size=None, mime=None, previewable=False)
        await validate_upload(db, size_bytes=len(file_bytes), filename=file_name or "")
        path = await asyncio.to_thread(
            save_upload, doc_id=doc_id, file_id=generate_file_id(), filename=file_name or "", data=file_bytes
        )
        return _FileMeta(
            path=path, name=file_name, size=len(file_bytes), mime=file_mime, previewable=is_previewable(file_mime or "")
        )

    async def _create_doc_with_retry(
        self, db: AsyncSession, *, category_code: str, doc_name: str, func_code: str | None, op: OperatorInfo
    ):
        """配號建立草稿文件；並發同分類撞號由 PK 擋 → SAVEPOINT 回退重取號重試（≤3 次）。"""
        for _ in range(_MAX_DOCID_RETRY):
            doc_id = await next_doc_id(db, category_code)
            try:
                async with db.begin_nested():  # SAVEPOINT：PK 衝突只回退本次 INSERT，不毀請求交易
                    return await self._repo.create_document(
                        db, doc_id=doc_id, doc_name=doc_name, category_code=category_code, func_code=func_code, op=op
                    )
            except IntegrityError:
                continue
        raise AppError(status_code=500, detail="文件編號配號失敗，請重試", error_code="DM_DOC_011")

    # ── 編輯新版本 ────────────────────────────────────

    async def add_version(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        audience_ids: Sequence[int],
        retrieval_ids: Sequence[int],
        version_no: str,
        change_summary: str,
        file_name: str | None,
        file_bytes: bytes | None,
        file_mime: str | None,
        op: OperatorInfo,
    ) -> VersionResult:
        """既有文件新增 DRAFT 版本（身份欄不吃）+ 覆寫文件層標籤（可見對象 / 檢索）。

        存草稿不卡必填（US5）：版號 / 摘要 / 檔案皆可空，送簽時才完整檢核。標籤為文件層（DM_DOC_TAG
        無 version_id），編輯時即時生效；前端編輯模式以 GET tags 端點預帶既有標籤供修改，避免誤清。
        """
        version_no = (version_no or "").strip()
        change_summary = (change_summary or "").strip()
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        # 廢止待簽核 → 不得上傳新版本（DM-MSG-DM03-004）
        if await self._repo.has_pending_obsolete(db, doc_id):
            raise AppError(status_code=409, detail="此文件廢止待簽核，無法上傳新版本", error_code="DM_DOC_008")
        # 每人每文件一份進行中版本（他人不擋）：已有草稿 → 請續編（DM_DOC_009）；已有審核中版本 → 擋，
        # 待審核結果再處理（DM_DOC_012）。同時擋審核中，杜絕「送審後又另開草稿」使退回無法一致轉回草稿。
        open_ver = await self._repo.get_author_open_version(db, doc_id, op.user_id)
        if open_ver is not None:
            if open_ver.status == _PENDING_REVIEW:
                raise AppError(
                    status_code=409,
                    detail="您對此文件已有審核中的版本，請待審核結果後再編輯",
                    error_code="DM_DOC_012",
                )
            raise AppError(
                status_code=409, detail="您已有此文件之未送簽草稿版本，請續編既有草稿", error_code="DM_DOC_009"
            )
        tag_ids = await self._validate_tags(db, audience_ids, retrieval_ids)
        fmeta = await self._store_file(
            db, doc_id=doc_id, file_name=file_name, file_bytes=file_bytes, file_mime=file_mime
        )
        try:
            async with db.begin_nested():  # SAVEPOINT：並發撞單一草稿（同人）只回退本次 INSERT
                ver = await self._repo.add_version(
                    db,
                    doc_id=doc_id,
                    version_no=version_no,
                    change_summary=change_summary,
                    file_name=fmeta.name,
                    file_path=fmeta.path,
                    file_size=fmeta.size,
                    file_mime=fmeta.mime,
                    op=op,
                )
        except IntegrityError as exc:
            # 並發後盾（每人每文件一份草稿之部分唯一索引）：回退後給友善錯誤。
            raise AppError(
                status_code=409, detail="您已有此文件之未送簽草稿版本，請續編既有草稿", error_code="DM_DOC_009"
            ) from exc
        await self._repo.set_tags(db, doc_id=doc_id, tag_ids=tag_ids, op=op)  # 文件層標籤覆寫（即時生效）
        await self._log(
            db,
            action_type="CREATE",
            operator_id=op.user_id,
            target=doc_id,
            after={"version_id": ver.version_id, "version_no": version_no},
        )
        return VersionResult(version_id=ver.version_id, previewable=fmeta.previewable)

    # ── 續編草稿（#222）──────────────────────────────

    async def get_draft_meta(self, db: AsyncSession, *, doc_id: str, user_id: str) -> DraftMeta:
        """續編模式 author-scoped 之編輯器 meta（供 DRAFT-status 文件亦可載，不經 DM02 詳細端點）。

        回文件名稱 / 分類 / func / 父文件狀態 + 本人現有 DRAFT 版本內容（版號 / 摘要 / 檔案）+
        （退回 / 撤回草稿之）前次指定審核者。名稱可編輯性依父文件狀態（DRAFT 可改、PUBLISHED 唯讀，Q1=A）。

        Raises:
            AppError: 查無文件 / 查無本人可續編之 DRAFT 版本 / 無權（404 DM_DOC_017）。
        """
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise AppError(status_code=404, detail="查無可續編之草稿或無權存取", error_code="DM_DOC_017")
        ver = await self._repo.get_author_open_version(db, doc_id, user_id)
        if ver is None or ver.status != _DRAFT:  # 僅本人之 DRAFT 版本可續編（PENDING_REVIEW / 無 → 無可續編草稿）
            raise AppError(status_code=404, detail="查無可續編之草稿或無權存取", error_code="DM_DOC_017")
        category_name = await self._repo.get_category_name(db, doc.category_code) or doc.category_code
        func_name = await self._repo.get_func_name(db, doc.func_code) if doc.func_code else None
        last = await self._repo.get_last_review(db, ver.version_id)
        # 退回 / 撤回草稿預帶前次指定審核者供參考；從未送審 → None
        prior_reviewer = last.assigned_reviewer if last is not None and last.status in (_REJECTED, _WITHDRAWN) else None
        return DraftMeta(
            doc_id=doc.doc_id,
            doc_name=doc.doc_name,
            category_code=doc.category_code,
            category_name=category_name,
            func_code=doc.func_code,
            func_name=func_name,
            doc_status=doc.status,
            name_editable=doc.status == _DRAFT,  # 首版草稿名稱可改；已發布文件之新版草稿唯讀
            draft_version_id=ver.version_id,
            version_no=ver.version_no,
            change_summary=ver.change_summary,
            file_name=ver.file_name,
            file_size=ver.file_size,
            previewable=is_previewable(ver.file_mime or "") if ver.file_mime else False,
            assigned_reviewer=prior_reviewer,
        )

    async def update_draft_version(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        version_id: int,
        doc_name: str | None,
        audience_ids: Sequence[int],
        retrieval_ids: Sequence[int],
        version_no: str,
        change_summary: str,
        file_name: str | None,
        file_bytes: bytes | None,
        file_mime: str | None,
        op: OperatorInfo,
    ) -> VersionResult:
        """續編：更新既有 DRAFT 版本（版號 / 摘要 / 檔案）+ 文件層標籤覆寫，不另開版本（不撞單一草稿唯一索引）。

        父文件為 DRAFT（首版草稿）時一併更新文件名稱（Q1=A）；父文件已發布（新版本草稿）時名稱唯讀、忽略 doc_name。
        檔案未附（file_bytes 空）則保留既有檔案。

        Raises:
            AppError: 查無文件 / 版本（404 DM_DOC_001）、非本人（403 DM_DRAFT_003）、非草稿版本（409 DM_DRAFT_004）、
                廢止待簽核（409 DM_DOC_008）。
        """
        version_no = (version_no or "").strip()
        change_summary = (change_summary or "").strip()
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        ver = await self._repo.get_version(db, doc_id, version_id)
        if ver is None:
            raise _NOT_FOUND
        if ver.created_user != op.user_id:
            raise AppError(status_code=403, detail="僅能續編本人之草稿", error_code="DM_DRAFT_003")
        if ver.status != _DRAFT:
            raise AppError(status_code=409, detail="僅草稿版本可續編", error_code="DM_DRAFT_004")
        # 廢止待簽核 → 不得上傳新版本（DM-MSG-DM03-004）
        if await self._repo.has_pending_obsolete(db, doc_id):
            raise AppError(status_code=409, detail="此文件廢止待簽核，無法上傳新版本", error_code="DM_DOC_008")
        tag_ids = await self._validate_tags(db, audience_ids, retrieval_ids)

        now = utcnow()
        previewable = is_previewable(ver.file_mime or "") if ver.file_mime else False
        if file_bytes:  # 有附新檔才落盤覆寫；否則保留既有檔案
            fmeta = await self._store_file(
                db, doc_id=doc_id, file_name=file_name, file_bytes=file_bytes, file_mime=file_mime
            )
            ver.file_name, ver.file_path, ver.file_size, ver.file_mime = fmeta.name, fmeta.path, fmeta.size, fmeta.mime
            previewable = fmeta.previewable
        ver.version_no, ver.change_summary = version_no, change_summary
        ver.updated_user, ver.updated_date = op.user_id, now
        if doc.status == _DRAFT and doc_name is not None:  # 首版草稿可改名（Q1=A）；已發布文件唯讀、忽略
            doc.doc_name = doc_name.strip()
            doc.updated_user, doc.updated_date = op.user_id, now
        await self._repo.set_tags(db, doc_id=doc_id, tag_ids=tag_ids, op=op)
        await db.flush()
        await self._log(
            db,
            action_type="UPDATE",
            operator_id=op.user_id,
            target=doc_id,
            after={"version_id": version_id, "version_no": version_no, "operation": "CONTINUE_DRAFT"},
        )
        return VersionResult(version_id=version_id, previewable=previewable)

    async def get_doc_tags(self, db: AsyncSession, doc_id: str) -> EditorDocTags:
        """取文件現有標籤（可見對象 / 檢索之 TAG_ID），供編輯模式表單預帶。查無文件 → 404。"""
        if await self._repo.get_document(db, doc_id) is None:
            raise _NOT_FOUND
        tags = await self._repo.get_doc_tags(db, doc_id)
        return EditorDocTags(audience_ids=tags["audience_ids"], retrieval_ids=tags["retrieval_ids"])

    # ── 送簽 ──────────────────────────────────────────

    async def submit(
        self, db: AsyncSession, *, doc_id: str, version_id: int, assigned_reviewer: str, op: OperatorInfo
    ) -> SubmitResult:
        """送簽：檢核 → 建 review（NEW|NEW_VERSION）→ 狀態轉移 → 通知審核者。"""
        assigned_reviewer = (assigned_reviewer or "").strip()
        _require(審核者=assigned_reviewer)
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        ver = await self._repo.get_version(db, doc_id, version_id)
        if ver is None:
            raise _NOT_FOUND
        # 版本須為草稿才可送簽：已送簽（PENDING_REVIEW）之版本再送即「已有進行中送審」；
        # 亦擋以已發布 / 終態版本之 version_id 誤送（防呆，避免翻動已發布版狀態）。
        if ver.status != _DRAFT:
            raise AppError(
                status_code=409, detail="此文件已有進行中之送審，無法同時送出另一種送審", error_code="DM_REVIEW_002"
            )
        # 指定審核者不可為「該版本撰寫者」本人（FR-006 不可自審）——以版本 CREATED_USER 為準，
        # 而非送簽者：他人代送草稿時，仍須排除實際撰寫者。ReviewService.submit 另擋送簽者本人。
        ensure_reviewer_not_author(assigned_reviewer, ver.created_user)
        await self._ensure_submittable(db, doc, ver)

        # 首版（文件仍 DRAFT）→ NEW；已發布文件之新版 → NEW_VERSION
        review_type = _NEW if doc.status == _DRAFT else _NEW_VERSION
        review = await self._reviews.submit(
            db,
            doc_id=doc_id,
            review_type=review_type,
            assigned_reviewer=assigned_reviewer,
            author_id=op.user_id,
            version_id=version_id,
        )

        # 狀態轉移：版本 DRAFT→PENDING_REVIEW；文件首版同轉、已發布文件維持 PUBLISHED
        now = utcnow()
        ver.status = _PENDING_REVIEW
        ver.updated_user, ver.updated_date = op.user_id, now
        if doc.status == _DRAFT:
            doc.status = _PENDING_REVIEW
            doc.updated_user, doc.updated_date = op.user_id, now
        await db.flush()

        await self._log(
            db,
            action_type="UPDATE",
            operator_id=op.user_id,
            target=doc_id,
            after={
                "review_id": review.review_id,
                "review_type": review_type,
                "version_id": version_id,
                "assigned_reviewer": assigned_reviewer,
            },
        )

        notified = await self._notify_submit(
            db,
            reviewer_id=assigned_reviewer,
            author_id=ver.created_user,  # 通知顯示實際撰寫者（非代送者）
            doc_name=doc.doc_name,
            review_type=review_type,
        )
        return SubmitResult(review_id=review.review_id, notified=notified)

    async def _ensure_submittable(self, db: AsyncSession, doc, ver) -> None:
        """送簽前完整檢核（存草稿階段皆放行、於此才要求）：版號 / 摘要 / 檔案 / MANUAL func /
        可見對象 ≥1 / 手冊唯一 / 廢止互斥。"""
        if not (ver.version_no or "").strip():
            raise AppError(status_code=422, detail="請輸入版本號", error_code="DM_DOC_006")
        if await self._repo.version_no_taken(db, doc.doc_id, ver.version_no):
            raise AppError(status_code=422, detail="版本號與本文件已發布版本重複", error_code="DM_DOC_006")
        if not (ver.change_summary or "").strip():
            raise AppError(status_code=422, detail="請填寫變更摘要", error_code="DM_DOC_004")
        if not ver.file_path:
            raise AppError(status_code=422, detail="請先上傳文件檔案", error_code="DM_DOC_004")
        if doc.category_code == _MANUAL and not doc.func_code:
            raise AppError(status_code=422, detail="系統操作手冊須指定關聯作業項目", error_code="DM_DOC_004")
        if not await self._repo.has_audience_tag(db, doc.doc_id):
            raise AppError(status_code=422, detail="文件至少需掛 1 個可見對象", error_code="DM_DOC_005")
        if (
            doc.category_code == _MANUAL
            and doc.func_code
            and await self._repo.manual_func_published_elsewhere(db, doc.func_code, doc.doc_id)
        ):
            raise AppError(status_code=409, detail="此關聯作業項目已有對應之已發布手冊", error_code="DM_DOC_007")
        if await self._repo.has_pending_obsolete(db, doc.doc_id):
            raise AppError(status_code=409, detail="此文件廢止待簽核，無法上傳新版本", error_code="DM_DOC_008")

    async def _notify_submit(
        self, db: AsyncSession, *, reviewer_id: str, author_id: str, doc_name: str, review_type: str
    ) -> int:
        """通知指定審核者（DOC_SUBMIT）；審核者查無 Email 則略過（回 0）。"""
        reviewer = await self._repo.get_user_name_email(db, reviewer_id)
        if reviewer is None or not reviewer.email:
            return 0
        author = await self._repo.get_user_name_email(db, author_id)
        result = await self._notifier.notify(
            db,
            template_code="DOC_SUBMIT",
            recipients=[reviewer.email],
            params={
                "reviewer_name": reviewer.user_name,
                "author_name": author.user_name if author else author_id,
                "doc_name": doc_name,
                "review_type": _REVIEW_TYPE_LABEL.get(review_type, review_type),
            },
        )
        return result.queued_count

    # ── 受控下拉 ──────────────────────────────────────

    async def list_reviewers(self, db: AsyncSession, *, op: OperatorInfo) -> list[ReviewerItem]:
        """列具 DM_REVIEWER 角色之使用者（排除自己）。"""
        rows = await self._repo.list_reviewers(db, exclude_user_id=op.user_id)
        return [ReviewerItem(user_id=r.user_id, user_name=r.user_name) for r in rows]

    async def get_options(self, db: AsyncSession) -> EditorOptions:
        """DM03 表單一次載入之受控下拉（分類 / func / 可見對象 / 檢索標籤，皆啟用中）。"""
        cats = await self._repo.list_categories(db)
        funcs = await self._repo.list_funcs(db)
        auds = await self._repo.list_audience_tags(db)
        rtags = await self._repo.list_retrieval_tags(db)
        return EditorOptions(
            categories=[OptionItem(code=c.category_code, name=c.category_name) for c in cats],
            funcs=[OptionItem(code=f.func_code, name=f.func_name) for f in funcs],
            audiences=[OptionItem(code=str(t.tag_id), name=t.tag_name) for t in auds],
            retrieval_tags=[
                OptionItem(code=str(t.tag_id), name=t.tag_name, group_code=t.tag_group_code) for t in rtags
            ],
        )

    # ── 內部檢核 ──────────────────────────────────────

    async def _ensure_category(self, db: AsyncSession, category_code: str) -> None:
        """分類須存在且啟用（受控輸入防呆 / 防竄改）。"""
        if not category_code or not await self._repo.category_enabled(db, category_code):
            raise AppError(status_code=422, detail="分類無效或已停用", error_code="DM_DOC_010")

    async def _resolve_func(self, db: AsyncSession, category_code: str, func_code: str | None) -> str | None:
        """非手冊類一律清為 None（不吃 func）；手冊類有填則驗證啟用（DM_DOC_010），未填允許
        （存草稿不卡，送簽時才要求 func）。"""
        if category_code != _MANUAL:
            return None
        func_code = (func_code or "").strip()
        if not func_code:
            return None
        if not await self._repo.func_enabled(db, func_code):
            raise AppError(status_code=422, detail="關聯作業項目無效或已停用", error_code="DM_DOC_010")
        return func_code

    async def _validate_tags(
        self, db: AsyncSession, audience_ids: Sequence[int], retrieval_ids: Sequence[int]
    ) -> list[int]:
        """驗證可見對象須屬 AUDIENCE 組、檢索標籤須屬 RETRIEVAL 型（皆啟用中）；回合併後之 tag_id 清單。"""
        all_ids = list(dict.fromkeys([*audience_ids, *retrieval_ids]))
        if not all_ids:
            return []
        kinds = await self._repo.classify_tags(db, all_ids)  # 僅啟用中者回傳
        for tid in audience_ids:
            if kinds.get(tid) != _AUDIENCE:
                raise AppError(status_code=422, detail="可見對象無效或已停用", error_code="DM_DOC_010")
        for tid in retrieval_ids:
            if kinds.get(tid) != _RETRIEVAL:
                raise AppError(status_code=422, detail="檢索標籤無效或已停用", error_code="DM_DOC_010")
        return all_ids


def _require(**fields: str) -> None:
    """必填欄位非空檢核（strip 後為空即失敗）；缺任一 → 422 DM_DOC_004（DM-MSG-DM03-001）。"""
    for name, value in fields.items():
        if not value:
            raise AppError(status_code=422, detail=f"必填欄位未填寫：{name}", error_code="DM_DOC_004")
