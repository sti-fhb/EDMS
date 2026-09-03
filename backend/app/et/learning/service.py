"""ET05 章節學習 Service（US5 / #255）。

## 課程關閉不過濾內容

#255 SA Q2 裁示 A：關閉 = **讀照舊、寫全停**。`is_closed` 只驅動前端的提示標示
（ET-MSG-ET05-005），**不影響任何一個端點回傳的內容**。

裁示依據為三個平台的實際做法：Canvas 的結課唯讀是「課程教材、討論、成績皆可看，
不可繳交 / 參與」；Moodle 的課程結束日期**預設完全不限制存取**（要擋須另外隱藏整門
課）；Hahow 為買斷無期限。**沒有一個平台依學習進度逐項過濾**。

`spec_us5` 原文寫「可重看**已學過的**教材」，本 issue 一併將措辭改為「課程教材」，
避免下一位實作者照字面做出過濾。

## 本 issue 不碰任何進度表

`locked` / `completed` 恆為 `False`——解鎖判定屬 `ET-5b`。欄位先備妥，`ET-5b` 交付時
只需換取值來源，前端不必再改一次。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.et.common.dm_client import get_dm_document_client
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, ITEM_MATERIAL
from app.et.learning.repository import EtLearningRepository
from app.et.learning.rules import ensure_can_access, playback_rates
from app.et.learning.schemas import (
    PREVIEWABLE_MIMES,
    ChapterNode,
    ItemNode,
    LearnStructure,
    MaterialContent,
    MaterialDocRow,
    MaterialVideoRow,
)
from app.et.material.storage import resolve_within_root
from app.services import ParamService

#: 倍速上限之參數代碼。單值參數，明細碼固定 `VALUE`（比照 #204 的邀請碼長度）。
_MAX_RATE_PARAM = "ET_VIDEO_PLAYBACK_MAX_RATE"
_DEFAULT_MAX_RATE = 2

_NOT_FOUND = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")
_DELETED = AppError(status_code=404, detail="此內容已刪除", error_code="ET_LEARN_003")

#: 取檔端點之統一「取不到」回應。
#:
#: ⚠️ **一律 404，不用 `ET_LEARN_002`（403）**：回 403 等於確認「這個 id 存在，只是你
#: 不能看」，可被用來枚舉全站有多少教材、哪些 id 有效。取檔端點對「不存在」與「無權」
#: 回同一個 404，外部觀察不到差異。比照 #247 `ET_ENROLL_001`（格式不符與查無共用同碼）。
_FILE_NOT_FOUND = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")


class EtLearningService:
    """學員端章節學習：結構、教材內容、取檔。"""

    def __init__(
        self,
        repository: EtLearningRepository | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or EtLearningRepository()
        self._params = params or ParamService()

    async def structure(self, db: AsyncSession, course_id: int, *, user_id: str) -> LearnStructure:
        """ET05 左側導覽之完整結構（AC 1 / AC 2）。

        Raises:
            AppError: 404 `ET_LEARN_001` 查無課程；403 `ET_LEARN_002` 非在籍且非擁有者。
        """
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        if course.status == COURSE_DRAFT and course.owner_id != user_id:
            # 未發布課程的**存在**對學員是秘密。若照一般流程回 403「您尚未加入此課程」，
            # 任一登入者（ET 學員角色人人有）即可用它二分掃描出全站有效 course_id，
            # 包含教師還沒發布的草稿。回 404 與「查無此課程」無法區分。
            #
            # 擁有者不受此限——教師需要在發布**之前**確認學員視角（#255 裁示 Q1 的
            # 同一個理由；草稿階段正是最需要預覽的時候）。
            raise _NOT_FOUND
        is_owner = await self._require_access(db, course_id=course_id, user_id=user_id, course_owner=course.owner_id)

        chapters = await self._repo.chapters(db, course_id)
        rows = await self._repo.items_with_titles(db, [c.chapter_id for c in chapters])
        by_chapter: dict[int, list[ItemNode]] = {}
        for item, material_name, quiz_name in rows:
            by_chapter.setdefault(item.chapter_id, []).append(
                ItemNode(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    sort_order=item.sort_order,
                    # 名稱取自對應子表；兩者皆無（資料異常）時給一個不會讓側欄出現空白列的預設。
                    title=(material_name if item.item_type == ITEM_MATERIAL else quiz_name) or "（未命名）",
                    material_id=item.material_id,
                    quiz_id=item.quiz_id,
                    locked=False,  # `ET-5b`
                    completed=False,  # `ET-5b`
                )
            )

        max_rate = await self._params.get_int_param(db, _MAX_RATE_PARAM, "VALUE", _DEFAULT_MAX_RATE)
        return LearnStructure(
            course_id=course.course_id,
            course_name=course.course_name,
            status=course.status,
            is_owner=is_owner,
            is_closed=course.status == COURSE_CLOSED,
            playback_rates=list(playback_rates(max_rate=max_rate)),
            chapters=[
                ChapterNode(
                    chapter_id=c.chapter_id,
                    chapter_name=c.chapter_name,
                    sort_order=c.sort_order,
                    items=by_chapter.get(c.chapter_id, []),
                )
                for c in chapters
            ],
        )

    async def material_content(self, db: AsyncSession, material_id: int, *, user_id: str) -> MaterialContent:
        """教材內容：說明文字 + 影片清單 + DM 文件清單（含廢止旗標）。"""
        # ⚠️ 順序要緊：**先授權、後回報刪除**。
        #
        # 授權走「不濾軟刪除」的反查鏈——否則教材被刪時 `course_id` 為 `None`，就得在
        # 「還不知道對方有沒有權限」的狀態下回應；此時若回「此內容已刪除」，等於向任何
        # 登入者確認「這個 material_id 曾經存在」。
        owning_course = await self._repo.course_id_of_material_any(db, material_id)
        if owning_course is None:
            raise _FILE_NOT_FOUND
        await self._require_access_by_course(db, course_id=owning_course, user_id=user_id)

        material = await self._repo.get_material(db, material_id)
        course_id = await self._repo.course_id_of_material(db, material_id)
        if material is None or course_id is None:
            # 有權者才看得到這個區別：教材本身或其所屬項目 / 章節任一被軟刪除（AC 22）。
            raise _DELETED
        if course_id != owning_course:
            # 授權是拿 `course_id_of_material_any`（不濾軟刪除、`limit(1)`）算的，而
            # 這裡是「活著的」那條。**同一份教材若被兩門課程引用**（今日不會發生——
            # 建項目一律產生新教材——但 `course/repository.py` 已預告日後可能支援重用），
            # 兩者就可能不同課程，於是「用 A 課的資格看 B 課的教材」。
            # 不一致即拒，不去猜哪一個才對。
            raise _FILE_NOT_FOUND

        videos = [
            MaterialVideoRow(
                video_id=v.video_id, file_name=v.file_name, duration_sec=v.duration_sec, sort_order=v.sort_order
            )
            for v in await self._repo.videos(db, material_id)
        ]
        # ⚠️ 逐份序列呼叫 DM（N+1）。**刻意不用 `asyncio.gather` 平行化**：
        # `AsyncSession` 不可跨協程並行共用，而 `get_current_by_doc_id` 是拿同一個
        # session 去查——平行化會踩到 SQLAlchemy 的並行使用錯誤，或更糟地靜默回錯資料。
        #
        # 實務上單一教材引用的 DM 文件是個位數（教師逐份挑選），故先接受。若日後成為
        # 瓶頸，正解是請 DM 開一支批次介面（`get_current_by_doc_ids`），而不是在這裡
        # 玩並行。
        docs = [await self._doc_row(db, d.doc_id, d.sort_order) for d in await self._repo.docs(db, material_id)]
        return MaterialContent(
            material_id=material.material_id,
            material_name=material.material_name,
            description_html=material.description_html,
            videos=videos,
            docs=docs,
        )

    async def ensure_video_accessible(self, db: AsyncSession, video_id: int, *, user_id: str) -> None:
        """發票前之授權：影片存在且該使用者有權（在籍 OR 擁有者）。

        **授權只在這裡做一次**——取檔端點憑票放行、不重跑（見 `video_ticket` 模組之
        取捨說明）。

        Raises:
            AppError: 404 `ET_LEARN_001`——不存在與無權共用同一回應。
        """
        video = await self._repo.get_video(db, video_id)
        course_id = await self._repo.course_id_of_video(db, video_id)
        if video is None or course_id is None:
            raise _FILE_NOT_FOUND
        await self._require_access_by_course(db, course_id=course_id, user_id=user_id)

    async def video_file_by_ticket(self, db: AsyncSession, video_id: int) -> tuple[str, str]:
        """憑票取檔：解析實體路徑與檔名（供 router 出 `FileResponse`）。

        **本方法不做授權**——呼叫端已驗票，而票的簽發經過 `ensure_video_accessible`。
        路徑一律經 `storage.resolve_within_root` 解析：`FILE_PATH` 存的是相對於
        `ET_VIDEO_STORAGE_ROOT` 的片段（#241），自行 `os.path.join` 等於開一個路徑
        穿越面。
        """
        video = await self._repo.get_video(db, video_id)
        if video is None:
            raise _FILE_NOT_FOUND
        return resolve_within_root(video.file_path, not_found=_FILE_NOT_FOUND), video.file_name

    async def doc_file(self, db: AsyncSession, material_id: int, doc_id: str, *, user_id: str):
        """DM 文件實體檔（經 `app/services` 之唯一跨模組出口）。

        `read_file_for_reference` 自帶 DM 側的 storage-root 圍籬與「僅當前版」限制
        （D-1），故此處不自行解析路徑。
        """
        course_id = await self._repo.course_id_of_material(db, material_id)
        if course_id is None:
            raise _FILE_NOT_FOUND
        await self._require_access_by_course(db, course_id=course_id, user_id=user_id)
        if not await self._repo.doc_belongs_to_material(db, material_id=material_id, doc_id=doc_id):
            # 未經此檢查，在籍任一課程者即可用自己有權的 material_id 搭配任意 doc_id
            # 取走全站被引用過的文件。
            raise _FILE_NOT_FOUND

        client = get_dm_document_client()
        try:
            current = await client.get_current_by_doc_id(db, doc_id)
            return await client.read_file_for_reference(db, doc_id=doc_id, version_id=current.current_version_id)
        except AppError as exc:
            # DM 端的錯誤碼（DM_DOC_*）不外洩給學員——對他而言就是取不到這份文件。
            raise _FILE_NOT_FOUND from exc

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _doc_row(self, db: AsyncSession, doc_id: str, sort_order: int) -> MaterialDocRow:
        """組單一 DM 文件列；DM 端查無時回 `available=False` 而非讓整個教材載入失敗。

        `ET_MATERIAL_DOC` **只存 `DOC_ID`、不存 version**（`data-model`），故引用一律
        指向當前發布版——wireframe 說的「自動帶最新版」是資料模型的必然結果。
        文件已廢止時 `CURRENT_VERSION_ID` 指向的正是廢止前最後一版，故「顯示廢止標籤」
        與「仍可閱讀最後版本」兩件事同時成立，不需另查歷史版本（AC 17）。
        """
        client = get_dm_document_client()
        try:
            current = await client.get_current_by_doc_id(db, doc_id)
        except AppError:
            return MaterialDocRow(
                doc_id=doc_id,
                doc_name=None,
                file_name=None,
                file_mime=None,
                version_id=None,
                obsolete=False,
                previewable=False,
                available=False,
                sort_order=sort_order,
            )
        return MaterialDocRow(
            doc_id=current.doc_id,
            doc_name=current.doc_name,
            file_name=current.file_name,
            file_mime=current.file_mime,
            version_id=current.current_version_id,
            obsolete=current.obsolete,
            previewable=current.file_mime in PREVIEWABLE_MIMES,
            available=True,
            sort_order=sort_order,
        )

    async def _require_access(self, db: AsyncSession, *, course_id: int, user_id: str, course_owner: str) -> bool:
        """判定並回傳 `is_owner`（供結構回應標示教師預覽模式）。"""
        is_owner = course_owner == user_id
        enrolled = await self._repo.is_enrolled(db, user_id=user_id, course_id=course_id)
        ensure_can_access(enrolled=enrolled, is_owner=is_owner)
        return is_owner

    async def _require_access_by_course(
        self, db: AsyncSession, *, course_id: int, user_id: str, not_found: AppError = _FILE_NOT_FOUND
    ) -> None:
        """同上，但由 `course_id` 反查擁有者；**無權一律收斂成 404**。

        本函式的三個呼叫端（教材內容、影片檔、DM 文件檔）都是**以 id 定址的資源**，
        回 403 等於確認「這個 id 存在，只是你不能看」——可用來枚舉全站有多少教材、
        哪些 id 有效。故此處不讓 `ET_LEARN_002`（403）冒出去。

        `ET_LEARN_002` 只用於 `/courses/{id}/learn`：課程的存在對學員不是秘密（他可能
        正要加入），而「你尚未加入此課程」是可行動的訊息。
        """
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise not_found
        try:
            await self._require_access(db, course_id=course_id, user_id=user_id, course_owner=course.owner_id)
        except AppError:
            raise not_found from None
