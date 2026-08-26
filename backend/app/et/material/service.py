"""ET 教材內容 Service（US3 / #203）。

**稽核**：沿用課程之功能碼 `ET-COURSE`——`spec.md` §稽核來源功能碼明列該碼涵蓋
「課程建立 / 編輯 / 發布 / 關閉 / 再開課，及其下章節、**教材**、測驗、問卷之編修與
刪除」，教材不另立功能碼。`target_id` 一律填**課程 ID**，使同一門課的所有異動在稽核
查詢上串得起來。

**授權**：教材無自己的擁有者概念——擁有權一律回溯至其所屬課程
（`EtItemRepository.resolve_owner` 單次 join）。找不到所屬課程者視為 404。

**跨模組**：DM 文件一律經 `app/services` 之 `DmDocumentService`（由
`app/et/common/dm_client.get_dm_document_client()` 取得），不得 `from app.dm`。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.et.common.dm_client import TRAINING_CATEGORY, get_dm_document_client
from app.et.common.html_sanitize import sanitize_material_html
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtItemRepository
from app.et.course.rules import ensure_owner
from app.et.material import storage
from app.et.material.repository import EtMaterialRepository
from app.et.material.rules import ensure_doc_not_duplicated, ensure_material_has_media
from app.et.material.schemas import (
    DmDocOption,
    DocRow,
    MaterialDetail,
    MaterialDocCreateReq,
    MaterialUpdateReq,
    VideoRow,
)
from app.et.material.video_probe import probe_duration_sec
from app.services import AuditLogService, ParamService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此教材", error_code="ET_MATERIAL_001")

#: 參數取不到時的保守預設值（與 `DP_PARAM` seed 一致）。參數被誤刪時寧可用預設值
#: 繼續服務，也不要讓整個上傳功能掛掉。
_DEFAULT_FORMATS = "mp4,webm"
_DEFAULT_MAX_SIZE_MB = 500


class EtMaterialService:
    """教材內容之讀取、編修與 DM 文件引用。"""

    def __init__(
        self,
        materials: EtMaterialRepository | None = None,
        items: EtItemRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._materials = materials or EtMaterialRepository()
        self._items = items or EtItemRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def get_detail(self, db: AsyncSession, material_id: int, *, actor_id: str) -> MaterialDetail:
        """教材詳細——影片與 DM 文件引用一次帶齊。"""
        material, _ = await self._require_owned(db, material_id, actor_id)
        videos = await self._materials.list_videos(db, material_id)
        docs = await self._materials.list_docs(db, material_id)
        return MaterialDetail(
            material_id=material.material_id,
            material_name=material.material_name,
            description_html=material.description_html,
            version=material.version,
            videos=[VideoRow.model_validate(v) for v in videos],
            docs=[await self._doc_row(db, d) for d in docs],
        )

    async def update(
        self, db: AsyncSession, material_id: int, req: MaterialUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新教材名稱與說明文字。

        兩件事的順序有意義：**先消毒、再檢核「至少擇一媒材」**。若通篇說明文字都是
        腳本，消毒後即為空——此時該教材若沒有影片也沒有文件，就是一個空教材，理應
        被 `ET_MATERIAL_002` 擋下。順序顛倒的話會放行一個看似有說明、實則空白的教材。
        """
        material, course_id = await self._require_owned(db, material_id, operator.user_id)
        description = sanitize_material_html(req.description_html)
        ensure_material_has_media(
            has_video=await self._materials.has_video(db, material_id),
            has_doc=await self._materials.has_doc(db, material_id),
            has_description=description is not None,
        )
        rowcount = await self._materials.update_basic(
            db,
            material_id,
            req.version,
            name=req.material_name,
            description_html=description,
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_MATERIAL")
        await self._log(db, "UPDATE", operator.user_id, course_id, "更新教材內容")

    async def upload_video(self, db: AsyncSession, material_id: int, upload, *, operator: OperatorInfo) -> VideoRow:
        """上傳一支教材影片。

        ## 步驟順序有意義

        1. 擁有權 → 2. 讀參數 → 3. 檢副檔名 → 4. **串流寫暫存檔**（邊寫邊數大小）
        → 5. **`ffprobe` 取長度**（取不到就刪暫存檔、拒收）→ 6. 搬到正式路徑
        → 7. 寫 DB 紀錄

        長度探測必須在檔案落地**之後**（ffprobe 要讀檔）、寫 DB **之前**
        （data-model：取不到不得存檔）。而搬檔放在寫 DB 之前是刻意的——
        見 `storage.promote` 對兩種失敗後果不對稱性的說明。

        寫 DB 失敗時刪掉正式檔：否則每次失敗的上傳都留一份 500 MB 的垃圾。
        """
        _, course_id = await self._require_owned(db, material_id, operator.user_id)

        formats_raw = await self._params.get_param_value(db, "ET_VIDEO_ALLOWED_FORMATS") or _DEFAULT_FORMATS
        max_size_mb = await self._params.get_int_param(db, "ET_VIDEO_MAX_SIZE_MB", "VALUE", _DEFAULT_MAX_SIZE_MB)
        ext = storage.ensure_format_allowed(upload.filename or "", formats_raw.split(","))

        tmp_path, size_bytes = await storage.save_video_stream(
            upload, ext=ext, max_size_bytes=max_size_mb * 1024 * 1024
        )
        try:
            duration_sec = await probe_duration_sec(tmp_path)
        except BaseException:
            storage.discard(tmp_path)
            raise

        final_path = storage.promote(tmp_path, video_id_hint=str(material_id), ext=ext)
        try:
            video = await self._materials.add_video(
                db,
                material_id,
                file_path=final_path,
                file_name=upload.filename or f"video.{ext}",
                duration_sec=duration_sec,
                file_size_bytes=size_bytes,
                operator=operator,
            )
        except BaseException:
            storage.discard(final_path)
            raise

        await self._log(db, "CREATE", operator.user_id, course_id, "上傳教材影片")
        return VideoRow.model_validate(video)

    async def delete_video(self, db: AsyncSession, video_id: int, *, operator: OperatorInfo) -> None:
        """刪除單支影片：本體與學員觀看紀錄軟刪，剩餘影片順序遞補。

        磁碟檔案**不刪**——軟刪除的語意是可回復（見 `repository.soft_delete_video`）。
        """
        video = await self._materials.get_video(db, video_id)
        if video is None:
            raise _NOT_FOUND
        _, course_id = await self._require_owned(db, video.material_id, operator.user_id)
        await self._materials.soft_delete_video(db, video_id, operator)
        await self._materials.resequence_videos(db, video.material_id, operator)
        await self._log(db, "DELETE", operator.user_id, course_id, "刪除教材影片")

    async def add_doc(
        self, db: AsyncSession, material_id: int, req: MaterialDocCreateReq, *, operator: OperatorInfo
    ) -> DocRow:
        """新增一筆 DM 文件引用。

        **先向 DM 確認該文件可引用**（SRVDM001）再落地：DM 端以 `AppError` 表達失敗
        （404 查無 / 非可引用分類、409 尚無發布版），直接讓它冒上去即可——ET 自行判斷
        會重複一次 DM 的分類白名單邏輯，兩邊遲早不一致。

        已廢止之文件**不在此擋下**：AC 只要求下拉不出現廢止文件、既有引用顯示警告。
        教師若手動帶入一個廢止文件的編號，仍會在課程發布檢核時被擋（屬 #204）。
        """
        _, course_id = await self._require_owned(db, material_id, operator.user_id)
        client = get_dm_document_client()
        await client.get_current_by_doc_id(db, req.doc_id)  # 不可引用 / 無發布版 → DM 端拋錯

        existing = await self._materials.list_docs(db, material_id)
        ensure_doc_not_duplicated(existing_doc_ids={d.doc_id for d in existing}, doc_id=req.doc_id)
        doc = await self._materials.add_doc(db, material_id, req.doc_id, operator)
        await self._log(db, "CREATE", operator.user_id, course_id, "新增教材文件引用")
        return await self._doc_row(db, doc)

    async def delete_doc(self, db: AsyncSession, mat_doc_id: int, *, operator: OperatorInfo) -> None:
        """刪除單筆文件引用（逐筆，不提供批次移除——AC 4）。"""
        doc = await self._materials.get_doc(db, mat_doc_id)
        if doc is None:
            raise _NOT_FOUND
        _, course_id = await self._require_owned(db, doc.material_id, operator.user_id)
        await self._materials.soft_delete_doc(db, mat_doc_id, operator)
        await self._log(db, "DELETE", operator.user_id, course_id, "刪除教材文件引用")

    async def list_dm_documents(self, db: AsyncSession, *, keyword: str = "") -> list[DmDocOption]:
        """DM 訓練教材下拉（SRVDM002）。

        DM 端已排除已廢止文件、保留「廢止待簽核」者——後者於該期間仍屬有效
        （data-model §ET_MATERIAL_DOC）。ET 這邊不再過濾，否則兩套判定會漂移。
        """
        client = get_dm_document_client()
        docs = await client.list_training_documents(db, category=TRAINING_CATEGORY, keyword=keyword)
        return [
            DmDocOption(
                doc_id=d.doc_id,
                doc_name=d.doc_name,
                version_no=d.version_no,
                published_date=d.published_date,
            )
            for d in docs
        ]

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_owned(self, db: AsyncSession, material_id: int, actor_id: str):
        """取教材並確認其所屬課程之擁有者為操作者。"""
        material = await self._materials.get(db, material_id)
        if material is None:
            raise _NOT_FOUND
        resolved = await self._items.resolve_owner(db, material_id=material_id)
        if resolved is None:
            raise _NOT_FOUND  # 孤兒教材：UI 無從到達，不揭露其存在
        course_id, owner_id = resolved
        ensure_owner(owner_id=owner_id, actor_id=actor_id)
        return material, course_id

    async def _doc_row(self, db: AsyncSession, doc) -> DocRow:
        """組出單筆引用列——名稱 / 版號 / 廢止狀態一律即時查 DM，不落地。

        DM 端取不到時（文件被刪、無發布版）**不讓例外冒上去**：教材詳細頁的職責是把
        現況呈現給教師，一份壞掉的引用不該讓整個視窗打不開。改以 `unavailable=True`
        標記，教師才看得到是哪一筆有問題並自行移除。
        """
        client = get_dm_document_client()
        try:
            current = await client.get_current_by_doc_id(db, doc.doc_id)
        except AppError:
            return DocRow(
                mat_doc_id=doc.mat_doc_id,
                doc_id=doc.doc_id,
                doc_name=None,
                version_no=None,
                obsolete=False,
                unavailable=True,
                sort_order=doc.sort_order,
            )
        return DocRow(
            mat_doc_id=doc.mat_doc_id,
            doc_id=doc.doc_id,
            doc_name=current.doc_name,
            version_no=current.version_no,
            obsolete=current.obsolete,
            unavailable=False,
            sort_order=doc.sort_order,
        )

    async def _log(self, db: AsyncSession, action: str, operator_id: str, course_id: int, description: str) -> None:
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type=action,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
        )
