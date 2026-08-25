"""ET02 課程 / 章節 / 課程標籤 Repository（US3 / #202）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。

**樂觀鎖以 rowcount 表達**：更新型方法回傳受影響列數，由 service 交給
`ensure_version_matched()` 判定（0 → 409 `ET_LOCK_001`）。Repository 不自行拋錯，
使「版本不符」與「查無資料」的區辨留在 service。
"""

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import COURSE_DRAFT, ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial
from app.et.material.repository import EtMaterialRepository
from app.et.progress.models import EtProgress
from app.et.quiz.models import EtQuiz
from app.et.quiz.repository import EtQuizRepository


class EtCourseRepository:
    """`ET_COURSE` 存取。"""

    async def create_draft(self, db: AsyncSession, data: dict, operator: OperatorInfo) -> EtCourse:
        """建立草稿課程。`OWNER_ID` 由 service 以 JWT 之 USER_ID 填入，不由請求帶入。"""
        course = EtCourse(
            **data,
            status=COURSE_DRAFT,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(course)
        await db.flush()
        return course

    async def get(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        """取單一課程（未刪除）。"""
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def update_basic(
        self, db: AsyncSession, course_id: int, version: int, data: dict, operator: OperatorInfo
    ) -> int:
        """更新基本資料並遞增 `VERSION`；回傳受影響列數供樂觀鎖判定。"""
        result = await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0, EtCourse.version == version)
            .values(
                **data,
                version=EtCourse.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, course_id: int, version: int, operator: OperatorInfo) -> int:
        """僅遞增課程 `VERSION`（章節重排用——重排是課程結構的變更）。"""
        result = await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0, EtCourse.version == version)
            .values(version=EtCourse.version + 1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()
        return result.rowcount

    async def soft_delete(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """軟刪除課程本體。其下章節與項目由 service 呼叫章節 repository 連動處理。"""
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()


class EtCourseTagRepository:
    """`ET_COURSE_TAG` 存取（課程×受訓單位標籤）。"""

    async def list_tag_ids(self, db: AsyncSession, course_id: int) -> set[int]:
        """課程現掛之 `TAG_ID` 集合。"""
        rows = await db.scalars(
            select(EtCourseTag.tag_id).where(EtCourseTag.course_id == course_id, EtCourseTag.deleted == 0)
        )
        return set(rows)

    async def list_active_tag_ids(self, db: AsyncSession, tag_ids: set[int]) -> set[int]:
        """給定集合中「啟用且未刪除」之 `TAG_ID`——供 service 擋下掛停用標籤。"""
        if not tag_ids:
            return set()
        rows = await db.scalars(
            select(EtTag.tag_id).where(EtTag.tag_id.in_(tag_ids), EtTag.deleted == 0, EtTag.is_active.is_(True))
        )
        return set(rows)

    async def apply(
        self, db: AsyncSession, course_id: int, *, to_add: set[int], to_remove: set[int], operator: OperatorInfo
    ) -> None:
        """差異套用：新增缺少者、軟刪除多餘者。

        以「重新啟用既有軟刪除列」而非插入新列處理 add——同一 (COURSE_ID, TAG_ID)
        反覆增刪時不會累積殭屍列，且保留最初的 `CREATED_DATE` 供追溯。
        """
        now = utcnow()
        if to_remove:
            await db.execute(
                update(EtCourseTag)
                .where(
                    EtCourseTag.course_id == course_id,
                    EtCourseTag.tag_id.in_(to_remove),
                    EtCourseTag.deleted == 0,
                )
                .values(deleted=1, updated_user=operator.user_id, updated_date=now)
            )
        if not to_add:
            await db.flush()
            return
        # 一次撈出待新增者中「已存在（含已軟刪除）」之列，避免逐個 tag 各發一次 SELECT
        existing_rows = await db.scalars(
            select(EtCourseTag).where(EtCourseTag.course_id == course_id, EtCourseTag.tag_id.in_(to_add))
        )
        existing_by_tag = {row.tag_id: row for row in existing_rows}
        for tag_id in to_add:
            existing = existing_by_tag.get(tag_id)
            if existing is None:
                db.add(
                    EtCourseTag(
                        course_id=course_id,
                        tag_id=tag_id,
                        created_user=operator.user_id,
                        created_date=now,
                    )
                )
            else:
                existing.deleted = 0
                existing.updated_user = operator.user_id
                existing.updated_date = now
        await db.flush()

    async def list_options(self, db: AsyncSession, course_id: int | None = None) -> list[EtTag]:
        """標籤下拉：啟用中之全部標籤，加上該課程既有已掛之停用標籤。

        FR-ET-US3-03：停用標籤排除於**可選**清單，但課程既有已掛者保留、不受影響
        ——故編輯既有課程時仍須回傳那些停用標籤，否則前端無從顯示已掛的 chip。
        """
        conds = [EtTag.is_active.is_(True)]
        if course_id is not None:
            conds.append(
                EtTag.tag_id.in_(
                    select(EtCourseTag.tag_id).where(EtCourseTag.course_id == course_id, EtCourseTag.deleted == 0)
                )
            )
        rows = await db.scalars(
            select(EtTag).where(EtTag.deleted == 0, or_(*conds)).order_by(EtTag.display_order, EtTag.tag_id)
        )
        return list(rows)


class EtChapterRepository:
    """`ET_CHAPTER` 存取，含刪除時之連動處理。"""

    async def list_by_course(self, db: AsyncSession, course_id: int) -> list[EtChapter]:
        """依 `SORT_ORDER` 列出課程之章節。"""
        rows = await db.scalars(
            select(EtChapter)
            .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
            .order_by(EtChapter.sort_order, EtChapter.chapter_id)
        )
        return list(rows)

    async def get(self, db: AsyncSession, chapter_id: int) -> EtChapter | None:
        return await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id, EtChapter.deleted == 0))

    async def append(self, db: AsyncSession, course_id: int, name: str, operator: OperatorInfo) -> EtChapter:
        """新增章節並追加至最末（`SORT_ORDER` = 現有最大值 + 1，自 1 起）。"""
        max_order = await db.scalar(
            select(func.max(EtChapter.sort_order)).where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
        )
        chapter = EtChapter(
            course_id=course_id,
            chapter_name=name,
            sort_order=(max_order or 0) + 1,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(chapter)
        await db.flush()
        return chapter

    async def rename(self, db: AsyncSession, chapter_id: int, version: int, name: str, operator: OperatorInfo) -> int:
        """更名並遞增 `VERSION`；回傳受影響列數供樂觀鎖判定。"""
        result = await db.execute(
            update(EtChapter)
            .where(EtChapter.chapter_id == chapter_id, EtChapter.deleted == 0, EtChapter.version == version)
            .values(
                chapter_name=name,
                version=EtChapter.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, chapter_id: int, version: int, operator: OperatorInfo) -> int:
        """僅遞增章節 `VERSION`（供項目重排之樂觀鎖）；回傳受影響列數。"""
        result = await db.execute(
            update(EtChapter)
            .where(EtChapter.chapter_id == chapter_id, EtChapter.deleted == 0, EtChapter.version == version)
            .values(
                version=EtChapter.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def apply_order(self, db: AsyncSession, order_map: dict[int, int], operator: OperatorInfo) -> None:
        """依 `{chapter_id: sort_order}` 批次更新順序（**兩階段寫入**）。

        **不檢核章節層 `VERSION`**——重排以課程層版本保護（見 service）。章節自身的
        `VERSION` 亦不遞增：順序屬課程結構，遞增會讓正在改章節名的另一裝置無故衝突。

        ## 為何要兩階段

        `UX_ET_CHAPTER_COURSE_ORDER` 為 `(COURSE_ID, SORT_ORDER)` 唯一索引。交換相鄰
        兩章（1↔2）時，若逐列直接寫入，第一列寫成 2 的瞬間會與尚未更新的第二列重複，
        PostgreSQL 立即拋 `UniqueViolationError`——非 deferrable 之唯一索引是**逐列
        即時檢核**，而部分索引（`WHERE DELETED = 0`）無法宣告 deferrable。

        故先把所有涉及之列移到**負數暫存區**（以目標順序取負，因目標順序本身唯一，
        負值亦唯一且不與任何正值業務資料衝突），再一次落定為正值。兩階段皆在同一
        交易內，外部看不到中間狀態。
        """
        if not order_map:
            return
        now = utcnow()
        for phase_value in (lambda target: -target, lambda target: target):
            for chapter_id, sort_order in order_map.items():
                await db.execute(
                    update(EtChapter)
                    .where(EtChapter.chapter_id == chapter_id, EtChapter.deleted == 0)
                    .values(
                        sort_order=phase_value(sort_order),
                        updated_user=operator.user_id,
                        updated_date=now,
                    )
                )
        await db.flush()

    async def soft_delete_with_cascade(self, db: AsyncSession, chapter_ids: list[int], operator: OperatorInfo) -> None:
        """軟刪除章節，並連動其下**所有項目**（教材 / 測驗）與學員紀錄。

        項目層的連帶處理已於 #203 抽至 `EtItemRepository.soft_delete_with_cascade`——
        #202 建立本方法時尚無項目端點，連帶範圍只到 `ET_PROGRESS` /
        `ET_QUIZ_ATTEMPT_M`；教材本體、影片、文件引用、題目、選項會被留成孤兒
        （章節刪了但教材列還在，無從到達亦不會被清）。

        改為委派後，「刪章節」與「逐一刪項目」的結果一致——否則兩條路徑會產生不同的
        殘留資料。
        """
        if not chapter_ids:
            return
        item_ids = list(
            await db.scalars(select(EtItem.item_id).where(EtItem.chapter_id.in_(chapter_ids), EtItem.deleted == 0))
        )
        await EtItemRepository().soft_delete_with_cascade(db, item_ids, operator)
        await db.execute(
            update(EtChapter)
            .where(EtChapter.chapter_id.in_(chapter_ids), EtChapter.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def resequence_remaining(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘章節之 `SORT_ORDER` 重編為 1..N（AC「後續章節順序自動遞補」）。"""
        remaining = await self.list_by_course(db, course_id)
        await self.apply_order(db, {c.chapter_id: i for i, c in enumerate(remaining, start=1)}, operator)


class EtItemRepository:
    """`ET_ITEM` 存取——章節下之教材 / 測驗項目，含刪除時之連動處理。"""

    def __init__(
        self,
        materials: EtMaterialRepository | None = None,
        quizzes: EtQuizRepository | None = None,
    ) -> None:
        self._materials = materials or EtMaterialRepository()
        self._quizzes = quizzes or EtQuizRepository()

    async def list_by_chapter(self, db: AsyncSession, chapter_id: int) -> list[EtItem]:
        """依 `SORT_ORDER` 列出章節之項目。"""
        rows = await db.scalars(
            select(EtItem)
            .where(EtItem.chapter_id == chapter_id, EtItem.deleted == 0)
            .order_by(EtItem.sort_order, EtItem.item_id)
        )
        return list(rows)

    async def get(self, db: AsyncSession, item_id: int) -> EtItem | None:
        return await db.scalar(select(EtItem).where(EtItem.item_id == item_id, EtItem.deleted == 0))

    async def list_rows_by_chapters(self, db: AsyncSession, chapter_ids: list[int]) -> list[tuple[EtItem, str]]:
        """一次取多個章節之項目與顯示名稱，回 `(item, title)`。

        以 outer join 取 `MATERIAL_NAME` / `QUIZ_NAME`——項目本身不存名稱（避免教材
        改名後不同步）。**批次查詢**：課程詳細頁一次要列出所有章節的項目，逐章節查
        會是 N+1。
        """
        if not chapter_ids:
            return []
        rows = await db.execute(
            select(EtItem, func.coalesce(EtMaterial.material_name, EtQuiz.quiz_name, ""))
            .outerjoin(EtMaterial, (EtItem.material_id == EtMaterial.material_id) & (EtMaterial.deleted == 0))
            .outerjoin(EtQuiz, (EtItem.quiz_id == EtQuiz.quiz_id) & (EtQuiz.deleted == 0))
            .where(EtItem.chapter_id.in_(chapter_ids), EtItem.deleted == 0)
            .order_by(EtItem.chapter_id, EtItem.sort_order, EtItem.item_id)
        )
        return [(row[0], row[1]) for row in rows.all()]

    async def append(
        self,
        db: AsyncSession,
        chapter_id: int,
        *,
        item_type: str,
        material_id: int | None = None,
        quiz_id: int | None = None,
        operator: OperatorInfo,
    ) -> EtItem:
        """新增項目並追加至章節最末（`SORT_ORDER` = 現有最大值 + 1，自 1 起）。

        `MATERIAL_ID` / `QUIZ_ID` 之互斥由 DB 之 `CK_ET_ITEM_TYPE_TARGET` 保證
        （#185 建立），此處僅負責填值。
        """
        max_order = await db.scalar(
            select(func.max(EtItem.sort_order)).where(EtItem.chapter_id == chapter_id, EtItem.deleted == 0)
        )
        item = EtItem(
            chapter_id=chapter_id,
            item_type=item_type,
            sort_order=(max_order or 0) + 1,
            material_id=material_id,
            quiz_id=quiz_id,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(item)
        await db.flush()
        return item

    async def apply_order(self, db: AsyncSession, order_map: dict[int, int], operator: OperatorInfo) -> None:
        """依 `{item_id: sort_order}` 批次更新順序（**兩階段寫入**）。

        兩階段的理由同章節（見 `EtChapterRepository.apply_order`）：
        `UX_ET_ITEM_CHAPTER_ORDER` 為非 deferrable 之部分唯一索引，逐列即時檢核，
        直接交換相鄰兩項會在中途撞鍵。先移至負數暫存區再落定。

        **不檢核項目層 `VERSION`、亦不遞增**——順序屬章節結構，遞增會讓正在編輯該教材
        內容的另一裝置無故衝突（FR-ET-US3-15「不同實體並行編輯互不衝突」）。
        """
        if not order_map:
            return
        now = utcnow()
        for phase_value in (lambda target: -target, lambda target: target):
            for item_id, sort_order in order_map.items():
                await db.execute(
                    update(EtItem)
                    .where(EtItem.item_id == item_id, EtItem.deleted == 0)
                    .values(
                        sort_order=phase_value(sort_order),
                        updated_user=operator.user_id,
                        updated_date=now,
                    )
                )
        await db.flush()

    async def soft_delete_with_cascade(self, db: AsyncSession, item_ids: list[int], operator: OperatorInfo) -> None:
        """軟刪除項目，並連動其教材 / 測驗本體與學員紀錄——**全部軟刪除**。

        1. `ET_PROGRESS`（學員於該項目之完成進度）
        2. 教材項目 → 委派 `EtMaterialRepository.soft_delete_cascade`
           （教材本體、影片、文件引用、學員觀看紀錄）
        3. 測驗項目 → 委派 `EtQuizRepository.soft_delete_cascade`
           （測驗本體、題目、選項、學員作答主檔與明細）

        **為何連教材 / 測驗本體一起刪**：`ET_ITEM.MATERIAL_ID` 雖無 UNIQUE、DB 層允許
        多個項目共用同一教材，但 UI 無「重用既有教材」入口，實務上恆為一項目一教材。
        不一起刪會留下無從到達的孤兒教材，且日後若真要支援重用，屆時本判斷需改為
        「僅在無其他項目引用時才刪」——那是加條件，不是推翻設計。
        """
        if not item_ids:
            return
        now = utcnow()
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": now}

        rows = await db.execute(
            select(EtItem.item_id, EtItem.item_type, EtItem.material_id, EtItem.quiz_id).where(
                EtItem.item_id.in_(item_ids), EtItem.deleted == 0
            )
        )
        items = rows.all()
        if not items:
            return

        live_ids = [row.item_id for row in items]
        material_ids = [row.material_id for row in items if row.item_type == ITEM_MATERIAL and row.material_id]
        quiz_ids = [row.quiz_id for row in items if row.item_type == ITEM_QUIZ and row.quiz_id]

        await db.execute(
            update(EtProgress).where(EtProgress.item_id.in_(live_ids), EtProgress.deleted == 0).values(**audit)
        )
        await self._materials.soft_delete_cascade(db, material_ids, operator)
        await self._quizzes.soft_delete_cascade(db, quiz_ids, operator)
        await db.execute(update(EtItem).where(EtItem.item_id.in_(live_ids)).values(**audit))
        await db.flush()

    async def resequence_remaining(self, db: AsyncSession, chapter_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘項目之 `SORT_ORDER` 重編為 1..N。"""
        remaining = await self.list_by_chapter(db, chapter_id)
        await self.apply_order(db, {item.item_id: i for i, item in enumerate(remaining, start=1)}, operator)
