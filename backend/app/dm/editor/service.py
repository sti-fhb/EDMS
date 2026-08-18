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

from collections.abc import Sequence

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
    EditorOptions,
    OptionItem,
    ReviewerItem,
    SubmitResult,
    VersionResult,
)
from app.dm.editor.storage import generate_file_id, save_upload
from app.dm.notify.service import DmNotifier
from app.dm.review.service import ReviewService

_DRAFT = "DRAFT"
_PENDING_REVIEW = "PENDING_REVIEW"
_MANUAL = "MANUAL"
_AUDIENCE = "AUDIENCE"
_RETRIEVAL = "RETRIEVAL"
_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"
_MAX_DOCID_RETRY = 3

_NOT_FOUND = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")
# 送審類型 → 通知範本人類可讀標籤（DOC_SUBMIT.review_type 變數）
_REVIEW_TYPE_LABEL = {_NEW: "首次發布審核", _NEW_VERSION: "新版本審核"}


class EditorService:
    """文件新增 / 編輯新版本 / 送簽 / 表單受控下拉。"""

    def __init__(
        self,
        repository: EditorRepository | None = None,
        reviews: ReviewService | None = None,
        notifier: DmNotifier | None = None,
    ) -> None:
        self._repo = repository or EditorRepository()
        self._reviews = reviews or ReviewService()
        self._notifier = notifier or DmNotifier()

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
        file_name: str,
        file_bytes: bytes,
        file_mime: str,
        op: OperatorInfo,
    ) -> CreateResult:
        """新增草稿文件（配 DOC_ID + DRAFT 首版 + 標籤）。首版無重複版號之虞。"""
        doc_name = (doc_name or "").strip()
        version_no = (version_no or "").strip()
        change_summary = (change_summary or "").strip()
        _require(文件名稱=doc_name, 版本號=version_no, 變更摘要=change_summary)
        await self._ensure_category(db, category_code)
        func_code = await self._resolve_func(db, category_code, func_code)
        tag_ids = await self._validate_tags(db, audience_ids, retrieval_ids)
        await validate_upload(db, size_bytes=len(file_bytes), filename=file_name)

        doc = await self._create_doc_with_retry(
            db, category_code=category_code, doc_name=doc_name, func_code=func_code, op=op
        )
        file_path = save_upload(doc_id=doc.doc_id, file_id=generate_file_id(), filename=file_name, data=file_bytes)
        ver = await self._repo.add_version(
            db,
            doc_id=doc.doc_id,
            version_no=version_no,
            change_summary=change_summary,
            file_name=file_name,
            file_path=file_path,
            file_size=len(file_bytes),
            file_mime=file_mime,
            op=op,
        )
        await self._repo.set_tags(db, doc_id=doc.doc_id, tag_ids=tag_ids, op=op)
        return CreateResult(doc_id=doc.doc_id, version_id=ver.version_id, previewable=is_previewable(file_mime))

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
        version_no: str,
        change_summary: str,
        file_name: str,
        file_bytes: bytes,
        file_mime: str,
        op: OperatorInfo,
    ) -> VersionResult:
        """既有文件新增 DRAFT 版本（身份欄不吃）。

        標籤 / 可見性為文件層且與目前發布版共用（DM_DOC_TAG 無 version_id），新版本一律**沿用**
        文件既有標籤、不於此變更——避免草稿期即改動已發布文件之可見性，且文件詳細（US4）未提供
        既有標籤 ID 供前端預帶。可見性 / 標籤之維護待專屬讀 API 到位後另議（見 PR 差異紀錄）。
        """
        version_no = (version_no or "").strip()
        change_summary = (change_summary or "").strip()
        _require(版本號=version_no, 變更摘要=change_summary)
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        # 廢止待簽核 → 不得上傳新版本（DM-MSG-DM03-004）
        if await self._repo.has_pending_obsolete(db, doc_id):
            raise AppError(status_code=409, detail="此文件廢止待簽核，無法上傳新版本", error_code="DM_DOC_008")
        # 單一草稿（Q1=A）：已有未送簽草稿 → 擋，請續編既有草稿
        if await self._repo.get_open_draft_version(db, doc_id) is not None:
            raise AppError(
                status_code=409, detail="此文件已有未送簽之草稿版本，請續編既有草稿", error_code="DM_DOC_009"
            )
        if await self._repo.version_no_taken(db, doc_id, version_no):
            raise AppError(status_code=422, detail="版本號未填或與本文件既有版本重複", error_code="DM_DOC_006")
        await validate_upload(db, size_bytes=len(file_bytes), filename=file_name)

        file_path = save_upload(doc_id=doc_id, file_id=generate_file_id(), filename=file_name, data=file_bytes)
        ver = await self._repo.add_version(
            db,
            doc_id=doc_id,
            version_no=version_no,
            change_summary=change_summary,
            file_name=file_name,
            file_path=file_path,
            file_size=len(file_bytes),
            file_mime=file_mime,
            op=op,
        )
        return VersionResult(version_id=ver.version_id, previewable=is_previewable(file_mime))

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

        # 送簽前檢核
        if not await self._repo.has_audience_tag(db, doc_id):
            raise AppError(status_code=422, detail="文件至少需掛 1 個可見對象", error_code="DM_DOC_005")
        if doc.category_code == _MANUAL and doc.func_code:
            if await self._repo.manual_func_published_elsewhere(db, doc.func_code, doc_id):
                raise AppError(status_code=409, detail="此關聯作業項目已有對應之已發布手冊", error_code="DM_DOC_007")
        if await self._repo.has_pending_obsolete(db, doc_id):
            raise AppError(status_code=409, detail="此文件廢止待簽核，無法上傳新版本", error_code="DM_DOC_008")

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

        notified = await self._notify_submit(
            db, reviewer_id=assigned_reviewer, author_id=op.user_id, doc_name=doc.doc_name, review_type=review_type
        )
        return SubmitResult(review_id=review.review_id, notified=notified)

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
        """系統操作手冊（MANUAL）必填且啟用之 func；非手冊類一律清為 None（不吃 func）。"""
        if category_code != _MANUAL:
            return None
        func_code = (func_code or "").strip()
        if not func_code:
            raise AppError(status_code=422, detail="系統操作手冊須指定關聯作業項目", error_code="DM_DOC_004")
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
