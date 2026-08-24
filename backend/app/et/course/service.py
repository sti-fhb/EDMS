"""ET02 課程骨架與章節編排 Service（US3 / #202）。

**稽核**：ET 於 `spec.md` §稽核來源功能碼明列 `ET-COURSE` 涵蓋「課程建立 / 編輯 /
發布 / 關閉 / 再開課，及其下章節、教材、測驗、問卷之編修與刪除」，故本模組之 CUD
一律寫 `DP_AUDIT_LOG`——此為 ET spec 對 `sti-backend-modules`「新模組預設不寫
audit log」之明文加嚴，非疏漏。

**授權分兩層**：
1. 建立課程須具「教師」角色（SA 裁示 Q2，#202）
2. 編輯 / 刪除 / 章節操作須為**擁有者**（`spec.md` §擁有權判定）

讀取端不套第 2 層——他人課程可閱覽，由回應之 `is_owner` 讓前端呈現唯讀。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtChapterRepository, EtCourseRepository, EtCourseTagRepository
from app.et.course.rules import (
    ensure_deletable,
    ensure_owner,
    ensure_reorder_complete,
    ensure_tag_change_allowed,
    resequence,
)
from app.et.course.schemas import (
    ChapterCreateReq,
    ChapterItem,
    ChapterRenameReq,
    ChapterReorderReq,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseUpdateReq,
    TagOption,
)
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_CHAPTER_NOT_FOUND = AppError(status_code=404, detail="查無此章節", error_code="ET_CHAPTER_001")


class EtCourseService:
    """課程骨架與章節編排。"""

    def __init__(
        self,
        courses: EtCourseRepository | None = None,
        tags: EtCourseTagRepository | None = None,
        chapters: EtChapterRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._courses = courses or EtCourseRepository()
        self._tags = tags or EtCourseTagRepository()
        self._chapters = chapters or EtChapterRepository()
        self._audit = audit or AuditLogService()

    # ── 課程 ────────────────────────────────────────────────────────────────

    async def create_draft(
        self, db: AsyncSession, req: CourseCreateReq, *, operator: OperatorInfo
    ) -> CourseCreateResult:
        """建立草稿課程並掛上受訓單位標籤。

        `OWNER_ID` 取自操作者，**不由請求帶入**——否則教師可代他人建立課程並繞過
        擁有權判定。呼叫端（router）須先以 `require_et_roles(ROLE_TEACHER)` 把關。
        """
        await self._ensure_tags_selectable(db, set(req.tag_ids))
        course = await self._courses.create_draft(
            db,
            {
                "course_name": req.course_name,
                "description": req.description,
                "open_start_at": req.open_start_at,
                "open_end_at": req.open_end_at,
                "require_approval": req.require_approval,
                "owner_id": operator.user_id,
            },
            operator,
        )
        if req.tag_ids:
            await self._tags.apply(db, course.course_id, to_add=set(req.tag_ids), to_remove=set(), operator=operator)
        await self._log(db, "CREATE", operator.user_id, course.course_id, "建立課程草稿")
        return CourseCreateResult(course_id=course.course_id, version=course.version)

    async def get_detail(self, db: AsyncSession, course_id: int, *, actor_id: str) -> CourseDetail:
        """課程詳細（含章節與標籤）。他人課程可閱覽，以 `is_owner` 表達可否編輯。"""
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        owner_name = await db.scalar(select(DpUser.user_name).where(DpUser.user_id == course.owner_id))
        tag_ids = await self._tags.list_tag_ids(db, course_id)
        chapters = await self._chapters.list_by_course(db, course_id)
        return CourseDetail(
            course_id=course.course_id,
            course_name=course.course_name,
            description=course.description,
            status=course.status,
            open_start_at=course.open_start_at,
            open_end_at=course.open_end_at,
            require_approval=course.require_approval,
            version=course.version,
            owner_id=course.owner_id,
            owner_name=owner_name,
            is_owner=course.owner_id == actor_id,
            tag_ids=sorted(tag_ids),
            chapters=[ChapterItem.model_validate(c) for c in chapters],
        )

    async def update_basic(
        self, db: AsyncSession, course_id: int, req: CourseUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新基本資料與標籤（全量覆寫）。"""
        course = await self._require_owned(db, course_id, operator.user_id)
        current = await self._tags.list_tag_ids(db, course_id)
        desired = set(req.tag_ids)
        ensure_tag_change_allowed(course.status, current=current, desired=desired)
        await self._ensure_tags_selectable(db, desired - current)

        rowcount = await self._courses.update_basic(
            db,
            course_id,
            req.version,
            {
                "course_name": req.course_name,
                "description": req.description,
                "open_start_at": req.open_start_at,
                "open_end_at": req.open_end_at,
                "require_approval": req.require_approval,
            },
            operator,
        )
        ensure_version_matched(rowcount, entity="ET_COURSE")
        await self._tags.apply(db, course_id, to_add=desired - current, to_remove=current - desired, operator=operator)
        await self._log(db, "UPDATE", operator.user_id, course_id, "編輯課程基本資料")

    async def delete_draft(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """刪除草稿課程（SA 裁示 Q1）：本體與其下章節 / 項目一併軟刪。

        已發布 / 已關閉課程改用 US11 之「關閉」——`ensure_deletable` 以
        `ET_COURSE_005` 擋下。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        ensure_deletable(course.status)
        chapters = await self._chapters.list_by_course(db, course_id)
        await self._chapters.soft_delete_with_cascade(db, [c.chapter_id for c in chapters], operator)
        await self._courses.soft_delete(db, course_id, operator)
        await self._log(db, "DELETE", operator.user_id, course_id, "刪除草稿課程")

    # ── 章節 ────────────────────────────────────────────────────────────────

    async def add_chapter(
        self, db: AsyncSession, course_id: int, req: ChapterCreateReq, *, operator: OperatorInfo
    ) -> ChapterItem:
        """新增章節，追加至最末。"""
        await self._require_owned(db, course_id, operator.user_id)
        chapter = await self._chapters.append(db, course_id, req.chapter_name, operator)
        await self._log(db, "CREATE", operator.user_id, course_id, "新增章節")
        return ChapterItem.model_validate(chapter)

    async def rename_chapter(
        self, db: AsyncSession, chapter_id: int, req: ChapterRenameReq, *, operator: OperatorInfo
    ) -> None:
        """更名章節（樂觀鎖檢核章節自身之 `VERSION`）。"""
        chapter = await self._chapters.get(db, chapter_id)
        if chapter is None:
            raise _CHAPTER_NOT_FOUND
        await self._require_owned(db, chapter.course_id, operator.user_id)
        rowcount = await self._chapters.rename(db, chapter_id, req.version, req.chapter_name, operator)
        ensure_version_matched(rowcount, entity="ET_CHAPTER")
        await self._log(db, "UPDATE", operator.user_id, chapter.course_id, "更名章節")

    async def reorder_chapters(
        self, db: AsyncSession, course_id: int, req: ChapterReorderReq, *, operator: OperatorInfo
    ) -> None:
        """重排章節順序。

        **以課程層 `VERSION` 保護**，非章節層——重排改動的是課程結構（多列同時變動），
        且若遞增各章節之 `VERSION`，正在改章節名的另一裝置會無故衝突，違反
        FR-ET-US3-15「不同實體並行編輯互不衝突」。
        """
        await self._require_owned(db, course_id, operator.user_id)
        current = await self._chapters.list_by_course(db, course_id)
        ensure_reorder_complete(current_ids={c.chapter_id for c in current}, requested=req.chapter_ids)
        rowcount = await self._courses.bump_version(db, course_id, req.version, operator)
        ensure_version_matched(rowcount, entity="ET_COURSE")
        await self._chapters.apply_order(db, resequence(req.chapter_ids), operator)
        await self._log(db, "UPDATE", operator.user_id, course_id, "調整章節順序")

    async def delete_chapter(self, db: AsyncSession, chapter_id: int, *, operator: OperatorInfo) -> None:
        """刪除章節：本體與其下項目軟刪、學員紀錄硬刪，剩餘章節順序遞補。"""
        chapter = await self._chapters.get(db, chapter_id)
        if chapter is None:
            raise _CHAPTER_NOT_FOUND
        await self._require_owned(db, chapter.course_id, operator.user_id)
        await self._chapters.soft_delete_with_cascade(db, [chapter_id], operator)
        await self._chapters.resequence_remaining(db, chapter.course_id, operator)
        await self._log(db, "DELETE", operator.user_id, chapter.course_id, "刪除章節")

    # ── 標籤下拉 ────────────────────────────────────────────────────────────

    async def list_tag_options(self, db: AsyncSession, *, course_id: int | None = None) -> list[TagOption]:
        """受訓單位標籤下拉（啟用中，加上該課程既有已掛之停用標籤）。"""
        return [TagOption.model_validate(t) for t in await self._tags.list_options(db, course_id)]

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_owned(self, db: AsyncSession, course_id: int, actor_id: str):
        """取課程並確認操作者為擁有者；查無 → 404、非擁有者 → 403。"""
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def _ensure_tags_selectable(self, db: AsyncSession, tag_ids: set[int]) -> None:
        """新掛之標籤須存在且啟用中（FR-ET-US3-03）。

        僅檢核**新增**的標籤——課程既有已掛之停用標籤保留、不受影響，若一併檢核會使
        「標籤被停用後該課程再也存不了檔」。
        """
        if not tag_ids:
            return
        active = await self._tags.list_active_tag_ids(db, tag_ids)
        if active != tag_ids:
            raise AppError(status_code=422, detail="指定之受訓單位標籤無效或未啟用", error_code="ET_COURSE_004")

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
