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
from app.core.utils import utcnow
from app.et.common.dm_client import TRAINING_CATEGORY, get_dm_document_client
from app.et.common.html_sanitize import sanitize_material_html
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtCourseRepository, EtItemRepository
from app.et.course.rules import ensure_owner, is_browsable_by_non_owner
from app.et.course.stage_rules import ENTITY_MATERIAL, ENTITY_MATERIAL_DOC, ENTITY_MATERIAL_VIDEO
from app.et.course.stage_writer import EtCourseStageWriter, exposed_id, is_staged
from app.et.material import storage
from app.et.material.repository import EtMaterialRepository
from app.et.material.rules import ensure_material_has_media, ensure_video_name_unused
from app.et.material.schemas import DmDocOption, DocRow, MaterialDetail, MaterialUpdateReq, VideoRow
from app.et.material.video_probe import probe_duration_sec
from app.services import AuditLogService, ParamService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此教材", error_code="ET_MATERIAL_001")

#: 參數取不到時的保守預設值（與 `DP_PARAM` seed 一致）。參數被誤刪時寧可用預設值
#: 繼續服務，也不要讓整個上傳功能掛掉。
_DEFAULT_FORMATS = "mp4,webm"
_DEFAULT_MAX_SIZE_MB = 500


def _ensure_browsable(*, owner_id: str, actor_id: str, status: str, open_end_at) -> None:
    """非擁有者只能讀「已發布且期間未過」的課程（#358 M-1 / `spec_us3` AC 8）。

    🔴 **這支只能用在讀取路徑。** 寫入路徑走 `ensure_owner`（403）——把本判定放進兩者
    共用的 `_resolve_*` helper 會讓非擁有者對他人**草稿**的寫入從 403 變成 404，而那
    三條寫入防護測試正是這樣抓到的。

    唯讀瀏覽的入口是 ET01「全部課程」清單，它只列符合此條件者；不判的話「清單上看
    不到、但用 id 直接打 API 讀得到他人草稿內容」。

    回 404 而非 403：與孤兒資源同一個處理，不揭露「這筆存在但你看不到」。比照
    `learning/service` 對學員連草稿的存在都不揭露。
    """
    if owner_id == actor_id:
        return
    if not is_browsable_by_non_owner(status=status, open_end_at=open_end_at, now=utcnow()):
        raise _NOT_FOUND


class EtMaterialService:
    """教材內容之讀取、編修與 DM 文件引用。"""

    def __init__(
        self,
        materials: EtMaterialRepository | None = None,
        items: EtItemRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
        courses: EtCourseRepository | None = None,
        stage_writer: EtCourseStageWriter | None = None,
    ) -> None:
        self._materials = materials or EtMaterialRepository()
        self._items = items or EtItemRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()
        self._courses = courses or EtCourseRepository()
        self._stage_writer = stage_writer or EtCourseStageWriter()

    async def get_detail(self, db: AsyncSession, material_id: int, *, actor_id: str) -> MaterialDetail:
        """教材詳細——影片與 DM 文件引用一次帶齊。

        ## 讀取端**不套擁有者判定**（#358 第 2 項）

        `FR-ET-US7-04` 與 US7 場景 8 明訂他人建立之課程可進入**唯讀瀏覽**，ET05 手冊亦
        寫「開啟他人建立的課程時進入檢視模式，所有欄位停用」——「停用」指不可編輯，
        不是看不到內容。

        原本此處走 `_require_owned`，於是教師乙開啟教師甲的課程、點開教材視窗會拿到
        403，畫面是**空白**（前端沒有錯誤呈現，就只是沒有內容）。同一頁的課後問卷卻
        正常顯示——因為 `survey/service.get_by_course` 早就是唯讀開放的。三者不一致。

        收斂方向為「可讀、不可寫」：本函式改為只驗存在，寫入路徑仍走 `_require_owned`。
        ⛔ **不可反過來把問卷也收緊**——那會讓檢視模式變成只看得到殼。

        角色門檻仍在 router（`require_et_roles(ET_TEACHER, ET_ADMIN)`），學員進不來。
        """
        # 🔴 **擁有者 + 已開始編輯 ⇒ 讀暫存版**（#631 PR 2b）。少了這段，教師開啟教材
        # 會看到活表（學員那一版）的內容，存檔時 `update_payload` 整份取代，他上一次
        # 的暫存編輯就被自己的畫面蓋回去了——而畫面上看不出任何異常。
        staged = await self._staged_detail(db, material_id, actor_id)
        if staged is not None:
            return staged

        material, resolved = await self._resolve_material(db, material_id)
        _ensure_browsable(
            owner_id=resolved.owner_id, actor_id=actor_id, status=resolved.status, open_end_at=resolved.open_end_at
        )
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

    async def _staged_detail(self, db: AsyncSession, material_id: int, actor_id: str) -> MaterialDetail | None:
        """暫存版的教材詳細；回 `None` 代表沒有暫存區、該走活表。

        ⚠️ **只對擁有者**：他人讀到的必須是學員看得到的那一版，否則「這門課有什麼」
        會有兩種答案（比照 `course/service.get_detail` 的同一道判斷）。

        ⚠️ 本函式**不取鎖**——它是讀取路徑。讀到一半被套用掉的話，教師看到的是套用後
        的內容，而那本來就是他接下來該編輯的基準。
        """
        node = await self._stage_writer.node_of(db, material_id, ENTITY_MATERIAL)
        if node is None:
            return None
        course = await self._courses.get(db, node.course_id)
        if course is None or course.owner_id != actor_id:
            return None
        children = await self._stage_writer.children_of(db, node.course_id, ENTITY_MATERIAL_VIDEO, node.stage_id)
        docs = await self._stage_writer.children_of(db, node.course_id, ENTITY_MATERIAL_DOC, node.stage_id)
        return MaterialDetail(
            material_id=material_id,
            material_name=str(node.payload.get("material_name") or ""),
            description_html=node.payload.get("description_html"),
            version=node.version,
            videos=[
                VideoRow(
                    video_id=exposed_id(source_id=v.source_id, stage_id=v.stage_id),
                    file_name=str(v.payload.get("file_name") or ""),
                    duration_sec=int(v.payload.get("duration_sec") or 0),
                    file_size_bytes=int(v.payload.get("file_size_bytes") or 0),
                    sort_order=v.sort_order,
                )
                for v in children
            ],
            docs=[await self._staged_doc_row(db, d) for d in docs],
        )

    async def update(
        self, db: AsyncSession, material_id: int, req: MaterialUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新教材：名稱、說明文字，與**完整的媒材集合**。

        ## 步驟順序有意義

        1. 擁有權 → 2. 消毒說明文字 → 3. 樂觀鎖更新本體 → 4. 套用文件 / 影片差異
        → 5. 對**最終狀態**檢核「至少擇一媒材」

        **先消毒再檢核**：通篇皆為腳本的說明文字消毒後即為空，此時若無影片也無文件
        就是空教材，理應被擋。順序顛倒會放行一個看似有說明、實則空白的教材。

        **檢核放在套用差異之後**：要驗的是「存檔後的樣子」，不是「存檔前的樣子」。
        放在前面的話，刪光所有文件的那次請求會以刪除前的狀態通過檢核。

        全部在同一交易內——任一步失敗（版本不符、引用了不可引用的文件、最終為空教材）
        整批回滾，使用者的畫面與 DB 不會分岔。
        """
        ref, course_id = await self._staged_material(db, material_id, operator.user_id, operator)
        description = sanitize_material_html(req.description_html)

        if ref is not None:
            # 已發布 / 已關閉：寫進暫存區，學員看到的仍是上一次「更新」的版本（#631）。
            # ⚠️ `update_payload` 是**整份取代**，所以兩個欄位都要送，缺一個會讓它消失
            # 而 `_upsert` 保留活表舊值——表現為「我把說明清空了，按更新卻還在」。
            rowcount = await self._stage_writer.update_payload(
                db,
                ref.stage_id,
                version=req.version,
                payload={"material_name": req.material_name, "description_html": description},
                operator=operator,
            )
            ensure_version_matched(rowcount=rowcount, entity="ET_MATERIAL")
            await self._apply_staged_docs(db, ref, req.doc_ids, operator)
            await self._apply_staged_videos(db, ref, req.video_ids, operator)
            # 檢核的對象同樣是**存檔後的樣子**，只是「後」指的是暫存區的最終狀態
            ensure_material_has_media(
                has_video=bool(
                    await self._stage_writer.children_of(db, ref.course_id, ENTITY_MATERIAL_VIDEO, ref.stage_id)
                ),
                has_doc=bool(
                    await self._stage_writer.children_of(db, ref.course_id, ENTITY_MATERIAL_DOC, ref.stage_id)
                ),
                has_description=description is not None,
            )
            await self._log(db, "UPDATE", operator.user_id, course_id, "更新教材內容（暫存）")
            return

        rowcount = await self._materials.update_basic(
            db,
            material_id,
            req.version,
            name=req.material_name,
            description_html=description,
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_MATERIAL")

        await self._apply_docs(db, material_id, req.doc_ids, operator)
        await self._apply_videos(db, material_id, req.video_ids, operator)

        ensure_material_has_media(
            has_video=await self._materials.has_video(db, material_id),
            has_doc=await self._materials.has_doc(db, material_id),
            has_description=description is not None,
        )
        await self._log(db, "UPDATE", operator.user_id, course_id, "更新教材內容")

    async def _apply_docs(self, db: AsyncSession, material_id: int, desired: list[str], operator: OperatorInfo) -> None:
        """把文件引用調整成 `desired`（新增缺的、刪除多的）。

        **只對新增的文件呼叫 SRVDM001**——既有引用不重驗：文件在 DM 端被廢止後仍是
        合法引用（廢止前最後版學員仍可讀），重驗會讓「只是改個教材名稱」的存檔因為
        某份舊文件被廢止而失敗。
        """
        existing = await self._materials.list_docs(db, material_id)
        existing_ids = {d.doc_id for d in existing}
        wanted = set(desired)

        for doc in existing:
            if doc.doc_id not in wanted:
                await self._materials.soft_delete_doc(db, doc.mat_doc_id, operator)

        client = get_dm_document_client()
        for doc_id in desired:
            if doc_id in existing_ids:
                continue
            await client.get_current_by_doc_id(db, doc_id)  # 不可引用 / 無發布版 → DM 端拋錯
            await self._materials.add_doc(db, material_id, doc_id, operator)

    async def _apply_staged_docs(self, db: AsyncSession, ref, desired: list[str], operator: OperatorInfo) -> None:
        """暫存版的 `_apply_docs`——差異同樣以 **`doc_id` 值**比對，不是以列的代理鍵。

        ⚠️ 新增的文件照樣要過 SRVDM001：那道檢核擋的是「引用了不可引用 / 無發布版的
        文件」，與內容何時生效無關。既有引用一樣不重驗（理由見 `_apply_docs`）。
        """
        existing = await self._stage_writer.children_of(db, ref.course_id, ENTITY_MATERIAL_DOC, ref.stage_id)
        existing_ids = {str(d.payload.get("doc_id")) for d in existing}
        wanted = set(desired)

        for node in existing:
            if str(node.payload.get("doc_id")) not in wanted:
                await self._stage_writer.delete_subtree(db, node.stage_id, operator)

        client = get_dm_document_client()
        for doc_id in desired:
            if doc_id in existing_ids:
                continue
            await client.get_current_by_doc_id(db, doc_id)  # 不可引用 / 無發布版 → DM 端拋錯
            await self._stage_writer.append(
                db,
                ref.course_id,
                ENTITY_MATERIAL_DOC,
                parent_stage_id=ref.stage_id,
                payload={"doc_id": doc_id},
                operator=operator,
            )

    async def _apply_staged_videos(self, db: AsyncSession, ref, keep: list[int], operator: OperatorInfo) -> None:
        """暫存版的 `_apply_videos`——同樣只刪不加（新增走上傳端點）。

        ⚠️ `keep` 內可能是**負數**（本次編輯剛上傳、活表還沒有的影片），所以比對要用
        `exposed_id` 而非 `source_id`。拿 `source_id` 比會讓剛上傳的影片每次存檔都被
        判定為「不在保留清單裡」而刪掉——檔案還在磁碟上，列卻消失。

        ⛔ 不在此處 resequence：暫存列的 `SORT_ORDER` 由 `apply_order` 或套用時的
        `_park_sort_orders` 處理，這裡刪完留洞沒有關係（暫存表沒有順序唯一索引）。
        """
        existing = await self._stage_writer.children_of(db, ref.course_id, ENTITY_MATERIAL_VIDEO, ref.stage_id)
        kept = set(keep)
        for node in existing:
            if exposed_id(source_id=node.source_id, stage_id=node.stage_id) not in kept:
                await self._stage_writer.delete_subtree(db, node.stage_id, operator)

    async def _apply_videos(self, db: AsyncSession, material_id: int, keep: list[int], operator: OperatorInfo) -> None:
        """刪除不在 `keep` 內的影片，並把剩餘影片順序遞補。

        影片**只能刪不能加**——新增走上傳端點（檔案無法暫存在 JSON 請求裡）。故此處
        不處理 `keep` 中不存在的 ID，那只會是前端送了一個已被別人刪掉的影片。
        """
        existing = await self._materials.list_videos(db, material_id)
        kept = set(keep)
        removed = [v.video_id for v in existing if v.video_id not in kept]
        if not removed:
            return
        for video_id in removed:
            await self._materials.soft_delete_video(db, video_id, operator)
        await self._materials.resequence_videos(db, material_id, operator)

    async def resolve_video_limits(self, db: AsyncSession) -> tuple[int, frozenset[str]]:
        """目前生效的 `(單檔上限 MB, 允許的影片格式集合)`。

        ## 🔴 這是**唯一**的解析處——驗證與「告訴教師能傳什麼」都走它（#455）

        改版前教材視窗的文案與 `accept` 是**寫死**的（「支援 mp4 / webm，單檔最大
        500 MB」），於是 IT 依既定途徑改了 `DP_PARAM` 之後，DP07 顯示新值、上傳畫面
        仍說舊話，而 `accept` 還會把新允許的格式擋在選檔器外——**教師看到的是「這個
        格式不能選」，不會有任何錯誤訊息告訴他為什麼**。

        ⛔ 不要為前端另寫一支「取得限制」的函式：兩支各自解析、各自 fallback，遲早
        分岔，而分岔的表徵就是「選得到卻傳不上去」。

        ⚠️ 參數缺值時退回種子預設（`mp4,webm` / 500 MB），**不是全部放行**。
        """
        formats_raw = await self._params.get_param_value(db, "ET_VIDEO_ALLOWED_FORMATS") or _DEFAULT_FORMATS
        max_size_mb = await self._params.get_int_param(db, "ET_VIDEO_MAX_SIZE_MB", "VALUE", _DEFAULT_MAX_SIZE_MB)
        formats = frozenset(f.strip().lower().lstrip(".") for f in formats_raw.split(",") if f.strip())
        return max_size_mb, (formats or frozenset(_DEFAULT_FORMATS.split(",")))

    async def upload_video(self, db: AsyncSession, material_id: int, upload, *, operator: OperatorInfo) -> VideoRow:
        """上傳一支教材影片。

        ## 為何上傳是即時的、而其餘媒材是暫存的

        檔案傳輸沒辦法「暫存在請求裡」——單檔上限 500 MB，留在瀏覽器記憶體等使用者
        按儲存並不可行。故上傳一選檔就送出，而說明文字、文件引用、影片刪除都留到
        按儲存時才隨 `PUT /materials/{id}` 一次套用。

        代價是：上傳後按取消，影片仍在。這不會造成空教材（多一個媒材不會少），
        使用者可再開啟教材把它刪掉。

        ## 步驟順序有意義

        1. 擁有權 → 2. 讀參數 → 3. 檢檔名長度與副檔名 → 4. **擋同名影片**（落地前）
        → 5. **串流寫暫存檔**（邊寫邊數大小）→ 6. **`ffprobe` 取長度**（取不到就刪
        暫存檔、拒收）→ 7. 搬到正式路徑 → 8. 寫 DB 紀錄

        長度探測必須在檔案落地**之後**（ffprobe 要讀檔）、寫 DB **之前**
        （data-model：取不到不得存檔）。搬檔放在寫 DB 之前是刻意的——見
        `storage.promote` 對兩種失敗後果不對稱性的說明。
        """
        ref, course_id = await self._staged_material(db, material_id, operator.user_id, operator)

        # ⚠️ 限制由 `resolve_video_limits` 解析——**前端的文案與 `accept` 走的是同一支**，
        # 兩邊因此不可能分岔（#455）。
        max_size_mb, formats = await self.resolve_video_limits(db)
        file_name = upload.filename or ""
        storage.ensure_file_name_acceptable(file_name)
        ext = storage.ensure_format_allowed(file_name, list(formats))

        # 在寫檔**之前**擋重複——等 500 MB 寫完才發現重複，I/O 與使用者的等待都白費。
        # ⚠️ 暫存模式要比對**暫存區**的檔名：比活表的話，教師這次剛上傳的同名檔不會被
        # 擋下，按「更新」時兩列一起進活表，教材就有兩支同名影片。
        if ref is not None:
            staged_videos = await self._stage_writer.children_of(db, ref.course_id, ENTITY_MATERIAL_VIDEO, ref.stage_id)
            existing_names = {str(v.payload.get("file_name") or "") for v in staged_videos}
        else:
            existing_names = {v.file_name for v in await self._materials.list_videos(db, material_id)}
        ensure_video_name_unused(existing_names=existing_names, file_name=file_name)

        tmp_path, size_bytes = await storage.save_video_stream(
            upload, ext=ext, max_size_bytes=max_size_mb * 1024 * 1024
        )
        try:
            duration_sec = await probe_duration_sec(tmp_path)
        except BaseException:
            storage.discard(tmp_path)
            raise

        # DB 記相對片段（可隨 root 搬移，#233）；回滾刪檔須用絕對路徑，兩者不可互換
        final_abs, final_rel = storage.promote(tmp_path, video_id_hint=str(abs(material_id)), ext=ext)
        try:
            if ref is not None:
                # 暫存模式：**檔案照樣落盤**（無從暫存），但列進暫存區，按「更新」才進活表。
                #
                # ⚠️ 已知代價：上傳後按「取消」放棄整個工作階段，磁碟上會留一個沒有任何
                # 列指向的檔。與既有的「上傳後按取消、影片仍在」同一性質，只是從「列還在、
                # 看得到、可自行刪除」變成「列沒了、看不到」。檔案不影響正確性（學員端讀
                # 不到沒有列的檔），清理待排 follow-up。
                stage_id = await self._stage_writer.append(
                    db,
                    ref.course_id,
                    ENTITY_MATERIAL_VIDEO,
                    parent_stage_id=ref.stage_id,
                    payload={
                        "file_path": final_rel,
                        "file_name": file_name or f"video.{ext}",
                        "duration_sec": duration_sec,
                        "file_size_bytes": size_bytes,
                    },
                    operator=operator,
                )
            else:
                video = await self._materials.add_video(
                    db,
                    material_id,
                    file_path=final_rel,
                    file_name=file_name or f"video.{ext}",
                    duration_sec=duration_sec,
                    file_size_bytes=size_bytes,
                    operator=operator,
                )
        except BaseException:
            storage.discard(final_abs)
            raise

        if ref is not None:
            await self._log(db, "CREATE", operator.user_id, course_id, "上傳教材影片（暫存）")
            return VideoRow(
                video_id=-stage_id,
                file_name=file_name or f"video.{ext}",
                duration_sec=duration_sec,
                file_size_bytes=size_bytes,
                sort_order=0,
            )

        await self._log(db, "CREATE", operator.user_id, course_id, "上傳教材影片")
        return VideoRow.model_validate(video)

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

    async def _resolve_material(self, db: AsyncSession, material_id: int):
        """取教材與其所屬課程，**不判擁有者**——供唯讀路徑使用。

        Returns:
            `(material, ResolvedCourse)`——後者含 `course_id` / `owner_id` / `status` /
            `open_end_at`，供呼叫端自行決定要套哪一道守門。

        ⚠️ 這支**不是**守門，只負責「存在嗎、掛在哪門課下」。讀取路徑要接
        `_ensure_browsable`，寫入路徑要接 `ensure_owner`（見 `_require_owned`）。
        把任何一道守門塞進本函式都會污染另一條路徑——#358 M-1 的第一版就是這樣讓
        非擁有者對他人草稿的寫入從 403 變成 404。
        """
        material = await self._materials.get(db, material_id)
        if material is None:
            raise _NOT_FOUND
        resolved = await self._items.resolve_owner(db, material_id=material_id)
        if resolved is None:
            raise _NOT_FOUND  # 孤兒教材：UI 無從到達，不揭露其存在
        return material, resolved

    async def _require_owned(self, db: AsyncSession, material_id: int, actor_id: str):
        """取教材並確認其所屬課程之擁有者為操作者——**寫入路徑專用**。

        讀取路徑請用 `_resolve_material`（#358 第 2 項：他人課程可唯讀瀏覽）。
        """
        material, resolved = await self._resolve_material(db, material_id)
        ensure_owner(owner_id=resolved.owner_id, actor_id=actor_id)
        return material, resolved.course_id

    async def _staged_material(self, db: AsyncSession, material_id: int, actor_id: str, operator):
        """教材 id → 暫存節點；回 `(None, course_id)` 代表該走活表路徑（#631 PR 2b）。

        形狀與 `course/service._staged_chapter` 完全相同，**刻意不抽成共用函式**：
        各模組解析「這個 id 屬於哪門課」的方式不一樣（教材要走
        `EtItemRepository.resolve_owner` 的 join），抽掉之後剩下的共用部分只有三行，
        而把三行包成一層會讓「授權排在取鎖之前」這件事變得不明顯。

        🔴 **負數先解析**：負數是本次編輯新增、活表還沒有的教材。
        🔴 **取鎖排在授權之後、解析之前**（理由見 `stage_writer.lock_course`）。
        """
        ref = await self._stage_writer.resolve_new(db, material_id, ENTITY_MATERIAL)
        if ref is not None:
            course = await self._courses.get(db, ref.course_id)
            if course is None:
                raise _NOT_FOUND
            ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            return ref, ref.course_id

        material, resolved = await self._resolve_material(db, material_id)
        ensure_owner(owner_id=resolved.owner_id, actor_id=actor_id)
        course = await self._courses.get(db, resolved.course_id)
        if not is_staged(course):
            return None, resolved.course_id
        await self._stage_writer.lock_course(db, resolved.course_id)
        ref = await self._stage_writer.ref_for_source(
            db, resolved.course_id, ENTITY_MATERIAL, material_id, operator, gone_error=_NOT_FOUND
        )
        return ref, resolved.course_id

    async def _staged_doc_row(self, db: AsyncSession, node) -> DocRow:
        """暫存版的 `_doc_row`——名稱 / 版號 / 廢止狀態一樣即時查 DM，不落地。

        ⚠️ `mat_doc_id` 回的是 `exposed_id`：既有引用回活表的代理鍵（與今天相同），
        本次新增的回負數。前端的刪除是把它從 `doc_ids` 拿掉、整份重送，所以這個值
        其實不參與寫入；但回錯會讓 React 的 key 撞號，畫面出現「刪了一筆、消失的是
        另一筆」。
        """
        doc_id = str(node.payload.get("doc_id") or "")
        mat_doc_id = exposed_id(source_id=node.source_id, stage_id=node.stage_id)
        client = get_dm_document_client()
        try:
            current = await client.get_current_by_doc_id(db, doc_id)
        except AppError:
            return DocRow(
                mat_doc_id=mat_doc_id,
                doc_id=doc_id,
                doc_name=None,
                version_no=None,
                obsolete=False,
                unavailable=True,
                sort_order=node.sort_order,
            )
        return DocRow(
            mat_doc_id=mat_doc_id,
            doc_id=doc_id,
            doc_name=current.doc_name,
            version_no=current.version_no,
            obsolete=current.obsolete,
            unavailable=False,
            sort_order=node.sort_order,
        )

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
