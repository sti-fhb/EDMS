"""文件詳細頁瀏覽服務（US4，唯讀 + 下載記錄）。

存取控制套 `visibility`（閱覽者不可取未授權文件）；編輯 / 廢止入口能力 `can_edit`（編輯者且無進行中
PENDING 送審週期）；檔案：舊版僅預覽、目前版可下載且下載寫 `DM_DOC_READ`（預覽不寫）。
"""

from dataclasses import dataclass

from app.core.exceptions import AppError
from app.dm.deps import DmContext
from app.dm.detail.repository import DetailRepository
from app.dm.detail.schemas import DetailResponse, FileMeta, ObsoleteInfo, VersionItem
from app.dm.document.file_paths import resolve_within_root
from app.dm.document.file_store import is_previewable
from app.dm.roles.authz import DM_EDITOR

_OBSOLETE = "OBSOLETE"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_NOT_FOUND = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")
_LOCK_OBSOLETE = "此文件廢止待簽核，暫無法編輯或再次廢止"
_LOCK_REVIEW = "此文件新版本送審中，暫無法編輯或廢止"
_LOCK_OWN_DRAFT = "您已有此文件的未送簽草稿，請續編既有草稿"


@dataclass(frozen=True)
class FileServe:
    """檔案端點回傳資訊（供 router 出 FileResponse）。"""

    path: str
    mime: str
    name: str
    inline: bool  # True=預覽 inline；False=下載 attachment


class DetailService:
    """文件詳細 / 版本 / 檔案存取。"""

    def __init__(self, repository: DetailRepository | None = None) -> None:
        self._repo = repository or DetailRepository()

    async def get_detail(self, db, *, doc_id: str, ctx: DmContext) -> DetailResponse:
        row = await self._repo.get_document(db, doc_id, ctx.user_id, ctx.roles)
        if row is None:
            raise _NOT_FOUND  # 查無或無權（存取控制）
        tags = await self._repo.get_retrieval_tags(db, doc_id)
        is_editor = DM_EDITOR in ctx.roles
        has_pending = await self._repo.has_pending_review(db, doc_id)
        # 本人已有未送簽草稿：編輯入口＝新開版本（addVersion），會被 DM_DOC_009 擋 → 提前灰階請續編既有草稿。
        # 送審中（不分申請人）優先於本人草稿：文件層送審鎖對所有編輯者一致失效。
        has_own_draft = (
            is_editor and not has_pending and await self._repo.author_has_open_draft(db, doc_id, ctx.user_id)
        )
        can_edit = is_editor and not has_pending and not has_own_draft
        # 入口失效原因（供前端灰階提示，非隱藏）：廢止待簽核 / 新版本送審中 / 本人已有草稿。
        edit_lock_reason = None
        if is_editor and has_pending:
            edit_lock_reason = _LOCK_OBSOLETE if row.status == _PENDING_OBSOLETE else _LOCK_REVIEW
        elif has_own_draft:
            edit_lock_reason = _LOCK_OWN_DRAFT
        is_obsolete = row.status == _OBSOLETE

        obsolete_info = None
        if is_obsolete:
            orv = await self._repo.get_obsolete_review(db, doc_id)
            if orv is not None:
                obsolete_info = ObsoleteInfo(
                    obsolete_time=orv.complete_date,
                    applicant_id=orv.applicant_id,
                    applicant_name=orv.applicant_name,
                    approver_name=orv.approver_name,
                    reason=orv.reason,
                    has_attachment=orv.obsolete_file_name is not None,
                )

        file_meta = None
        if row.version_id is not None:
            file_meta = FileMeta(
                version_id=row.version_id,
                file_name=row.file_name,
                file_mime=row.file_mime,
                file_size=row.file_size,
                uploaded_at=row.version_created,
                previewable=is_previewable(row.file_mime),
            )

        return DetailResponse(
            doc_id=row.doc_id,
            doc_name=row.doc_name,
            status=row.status,
            current_version_no=row.version_no,
            category_code=row.category_code,
            category_name=row.category_name,
            author_id=row.author_id,
            author_name=row.author_name,
            published_date=row.published_date,
            approver_id=row.approver_id,
            approver_name=row.approver_name,
            approve_time=row.published_date,
            tags=tags,
            func_code=row.func_code,
            func_name=row.func_name,
            file=file_meta,
            is_editor=is_editor,
            can_edit=can_edit,
            edit_lock_reason=edit_lock_reason,
            is_obsolete=is_obsolete,
            obsolete_info=obsolete_info,
        )

    async def list_versions(self, db, *, doc_id: str, ctx: DmContext) -> list[VersionItem]:
        meta = await self._repo.get_document_meta(db, doc_id, ctx.user_id, ctx.roles)
        if meta is None:
            raise _NOT_FOUND
        current_id = meta.current_version_id
        # 版本歷程不分角色僅列歷來發布版（PUBLISHED / SUPERSEDED）。
        rows = await self._repo.get_versions(db, doc_id)
        return [
            VersionItem(
                version_id=r.version_id,
                version_no=r.version_no,
                change_summary=r.change_summary,
                file_name=r.file_name,
                author_id=r.author_id,
                author_name=r.author_name,
                approver_name=r.approver_name,
                published_date=r.published_date,
                is_current=r.version_id == current_id,
                previewable=is_previewable(r.file_mime),
            )
            for r in rows
        ]

    async def prepare_file(self, db, *, doc_id: str, version_id: int, disposition: str, ctx: DmContext) -> FileServe:
        """檔案存取決策：套存取控制 → 舊版擋下載 → 非可預覽擋預覽 → 目前版下載寫 DM_DOC_READ。"""
        meta = await self._repo.get_document_meta(db, doc_id, ctx.user_id, ctx.roles)
        if meta is None:
            raise _NOT_FOUND
        # 僅供歷來發布版（PUBLISHED / SUPERSEDED）取檔；進行中 / 未通過版本一律不供（不分角色）。
        vfile = await self._repo.get_version_file(db, doc_id, version_id)
        if vfile is None:
            raise _NOT_FOUND
        # storage-root 圍籬（#160）：FILE_PATH 逃逸出根目錄 → 404，且在寫 DM_DOC_READ 等副作用前先擋。
        safe_path = resolve_within_root(vfile.file_path)
        is_current = version_id == meta.current_version_id

        if disposition == "download":
            if not is_current:  # 舊版僅預覽、不開放下載（FR-004）
                raise AppError(status_code=403, detail="舊版本不可下載，請聯絡管理者", error_code="DM_DOC_002")
            await self._repo.write_read(db, doc_id=doc_id, version_id=version_id, user_id=ctx.user_id)  # 已看
            return FileServe(path=safe_path, mime=vfile.file_mime, name=vfile.file_name, inline=False)

        # disposition == "preview"
        if not is_previewable(vfile.file_mime):  # Office 等無法線上預覽（FR-002 / DM-MSG-DM02-001）
            raise AppError(status_code=422, detail="此檔案格式無法線上預覽，請下載原檔", error_code="DM_DOC_003")
        return FileServe(path=safe_path, mime=vfile.file_mime, name=vfile.file_name, inline=True)
