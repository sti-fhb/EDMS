"""ET02 課程 / 章節 / 課程標籤 Repository（US3 / #202）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。

**樂觀鎖以 rowcount 表達**：更新型方法回傳受影響列數，由 service 交給
`ensure_version_matched()` 判定（0 → 409 `ET_LOCK_001`）。Repository 不自行拋錯，
使「版本不符」與「查無資料」的區辨留在 service。
"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import COURSE_DRAFT
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.progress.models import EtProgress
from app.et.quiz.models import EtQuizAttemptM


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
        for tag_id in to_add:
            existing = await db.scalar(
                select(EtCourseTag).where(EtCourseTag.course_id == course_id, EtCourseTag.tag_id == tag_id)
            )
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
        stmt = select(EtTag).where(EtTag.deleted == 0, EtTag.is_active.is_(True))
        if course_id is not None:
            attached = select(EtCourseTag.tag_id).where(EtCourseTag.course_id == course_id, EtCourseTag.deleted == 0)
            stmt = select(EtTag).where(
                EtTag.deleted == 0,
                (EtTag.is_active.is_(True)) | (EtTag.tag_id.in_(attached)),
            )
        rows = await db.scalars(stmt.order_by(EtTag.display_order, EtTag.tag_id))
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
        """軟刪除章節，並依 data-model 之三段連動處理其下資料。

        1. `ET_ITEM` → 軟刪除（連動）
        2. 學員 `ET_PROGRESS` → **hard delete**
        3. 學員 `ET_QUIZ_ATTEMPT_M` → **hard delete**

        ⚠️ 第 2、3 點與專案預設之軟刪除策略**相反**，是 ET 的刻意例外
        （data-model §ET_CHAPTER 業務規則）：章節已不存在，留著學員紀錄只會成為
        永遠查不到對應項目的孤兒資料，污染日後的進度統計與成績查詢。

        本 issue（#202）尚無建立項目之端點（屬 #203），故實務上 `item_ids` 目前恆為空；
        邏輯仍寫在此處——刪除是本 issue 交付的路徑，#203 接上項目後即自動生效，
        不必回頭補。
        """
        if not chapter_ids:
            return
        now = utcnow()

        item_rows = await db.execute(
            select(EtItem.item_id, EtItem.quiz_id).where(EtItem.chapter_id.in_(chapter_ids), EtItem.deleted == 0)
        )
        items = item_rows.all()
        item_ids = [row.item_id for row in items]
        quiz_ids = [row.quiz_id for row in items if row.quiz_id is not None]

        if item_ids:
            await db.execute(
                update(EtItem)
                .where(EtItem.item_id.in_(item_ids))
                .values(deleted=1, updated_user=operator.user_id, updated_date=now)
            )
            await db.execute(delete(EtProgress).where(EtProgress.item_id.in_(item_ids)))
        if quiz_ids:
            await db.execute(delete(EtQuizAttemptM).where(EtQuizAttemptM.quiz_id.in_(quiz_ids)))

        await db.execute(
            update(EtChapter)
            .where(EtChapter.chapter_id.in_(chapter_ids), EtChapter.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=now)
        )
        await db.flush()

    async def resequence_remaining(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘章節之 `SORT_ORDER` 重編為 1..N（AC「後續章節順序自動遞補」）。"""
        remaining = await self.list_by_course(db, course_id)
        await self.apply_order(db, {c.chapter_id: i for i, c in enumerate(remaining, start=1)}, operator)
