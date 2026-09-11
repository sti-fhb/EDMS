"""ET02 課程 / 章節 / 課程標籤 Repository（US3 / #202）；亦含 ET01 課程清單（US7 / #299）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。

**樂觀鎖以 rowcount 表達**：更新型方法回傳受影響列數，由 service 交給
`ensure_version_matched()` 判定（0 → 409 `ET_LOCK_001`）。Repository 不自行拋錯，
使「版本不符」與「查無資料」的區辨留在 service。
"""

from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.like_escape import LIKE_ESCAPE_CHAR
from app.core.like_escape import contains as like_contains
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED, ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial
from app.et.material.repository import EtMaterialRepository
from app.et.progress.models import EtEnrollment, EtProgress
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

    async def mark_published(
        self,
        db: AsyncSession,
        course_id: int,
        version: int,
        *,
        invitation_code: str,
        published_at: datetime,
        operator: OperatorInfo,
    ) -> int | None:
        """發布課程：狀態轉 `PUBLISHED`、寫入邀請碼與首次發布時間（#204）。

        `FIRST_PUBLISHED_AT` 以 `COALESCE` 保留既有值——歷經再開課（`ET-11`）不變
        （data-model §ET_COURSE）。本 issue 只由草稿發布一次，但寫法先對，避免
        `ET-11` 接手時把首次發布時間覆寫成再開課時間。

        帶樂觀鎖：檢核與寫入之間若有人改動課程，回 `None`，呼叫端據此讓教師重新載入
        ——而不是拿一份過時的檢核結果硬寫。

        ⚠️ **#288 改為以 `RETURNING` 回新版本**（原為 rowcount）。原本呼叫端寫
        `PublishResult(version=course.version + 1)`，但 `update(EtCourse)` 是
        ORM-enabled UPDATE、SQLAlchemy 會同步 identity map，執行後 `course.version`
        **已經是新值**——再 `+ 1` 就回了一個比 DB 大 1 的版本。那個值沒有造成使用者
        可見的問題（前端只顯示回應裡的邀請碼，寫入用的是 `GET /courses/{id}` 重抓的
        版本），但它是一個 API 回應裡的錯誤資料，且 #288 的 `mark_closed` /
        `mark_reopened` 若照抄同一形狀會讓測試必須把那個謊寫進斷言。

        Returns:
            新的 `VERSION`；`None` = 沒有列符合（版本不符）。
        """
        return await db.scalar(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0, EtCourse.version == version)
            .values(
                status=COURSE_PUBLISHED,
                invitation_code=invitation_code,
                first_published_at=func.coalesce(EtCourse.first_published_at, published_at),
                version=EtCourse.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
            .returning(EtCourse.version)
        )

    async def mark_closed(
        self, db: AsyncSession, course_id: int, version: int, *, closed_at: datetime, operator: OperatorInfo
    ) -> int | None:
        """關閉課程：狀態轉 `CLOSED`、寫入最近一次關閉時間（US11 AC 1）。

        ## 刻意不動 `OPEN_END_AT`

        手動關閉與到期關閉的差別就在這裡——手動關閉時閱課期間可能還沒到，把
        `OPEN_END_AT` 一併改成 `now` 會讓「為什麼關的」這個資訊消失，而 `CLOSED_AT`
        已經記錄了時點。再開課時兩個時間都會被強制覆寫，也不需要先清掉。

        `INVITATION_CODE` 亦不動：關閉期間邀請碼**失效但不作廢**（Clarifications 明訂
        再開課沿用原碼、不重產），失效是由各處守門判 `STATUS` 達成的。

        ## 以 `RETURNING` 回新版本，不由呼叫端自行 `+ 1`

        `update(EtCourse)` 是 **ORM-enabled UPDATE**，SQLAlchemy 會同步 identity map
        ——執行後手上那個 `EtCourse` 物件的 `version` **已經是新值**。呼叫端若再寫
        `course.version + 1` 就會多加一次，回給前端一個比 DB 大 1 的版本，而前端下一次
        帶它寫入必然 409。

        > `publish` 的 `PublishResult.version` 目前就是這個形狀（回 `course.version + 1`
        > 而 DB 已是該值）。它沒有造成使用者可見的問題，因為前端用的是
        > `GET /courses/{id}` 重抓的值、不消費那個欄位——已於 #288 的 PR 說明提出。
        > 本方法以 `RETURNING` 明確回值，不依賴上述同步行為。

        Returns:
            新的 `VERSION`；`None` = 沒有列符合（版本不符），呼叫端據此拋
            `ET_LOCK_001`。
        """
        return await db.scalar(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0, EtCourse.version == version)
            .values(
                status=COURSE_CLOSED,
                closed_at=closed_at,
                version=EtCourse.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
            .returning(EtCourse.version)
        )

    async def mark_reopened(
        self,
        db: AsyncSession,
        course_id: int,
        version: int,
        *,
        open_start_at: datetime,
        open_end_at: datetime,
        operator: OperatorInfo,
    ) -> int | None:
        """再開課：狀態回 `PUBLISHED`、覆寫新起訖時間、加急提醒旗標歸零（US11 AC 8）。

        ## 三個欄位刻意**不動**

        - `CLOSED_AT`：保留最近一次關閉時間供追溯（FR-ET-US11-10 明訂）
        - `FIRST_PUBLISHED_AT`：歷經再開課不變（`data-model` §ET_COURSE；`mark_published`
          已用 `COALESCE` 為此預留）
        - `INVITATION_CODE`：沿用原 8 碼、不重產（Clarifications 明訂），恢復有效是由
          各處守門判 `STATUS` 自動達成的

        `URGENT_REMIND_SENT` 必須歸 `false`——否則依新起訖時間算出的訖止前 3 天加急提醒
        不會再發（`ET-16` / SCHET002 以該旗標判斷是否已寄）。

        Returns:
            新的 `VERSION`；`None` = 版本不符（理由同 `mark_closed`）。
        """
        return await db.scalar(
            update(EtCourse)
            .where(EtCourse.course_id == course_id, EtCourse.deleted == 0, EtCourse.version == version)
            .values(
                status=COURSE_PUBLISHED,
                open_start_at=open_start_at,
                open_end_at=open_end_at,
                urgent_remind_sent=False,
                version=EtCourse.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
            .returning(EtCourse.version)
        )

    def build_list_stmt(
        self,
        *,
        actor_id: str,
        scope: str,
        keyword: str | None = None,
        tag_id: int | None = None,
        owner_id: str | None = None,
        now: datetime,
    ):
        """ET01 課程清單的查詢（`FR-ET-US7-01`/`-02`），供 `paginate()` 使用。

        ## 兩種 scope 的狀態過濾**相反**

        | scope | 擁有者 | 狀態 |
        |---|---|---|
        | `mine` | 限本人 | **全部**（草稿 / 已發布 / 已關閉）——教師要管理自己的課 |
        | `all` | 不限 | **僅已發布且期間未過**——見下 |

        ## `all` 的「已發布」是 `is_effectively_closed` 的否定，不是 `STATUS` 比對

        #288 立了「`PUBLISHED` 但 `OPEN_END_AT` 已過 = 視同關閉」的規則，且明訂呼叫端
        一律以「與 `CLOSED` 相同」處理。若此處只比對 `STATUS = 'PUBLISHED'`，期間已過
        的課程會留在「全部課程」——而學員早已進不去（邀請碼失效、進度寫入 409）。教師
        點進去看到的是一門對外已死的課，卡片卻標著「已發布」。

        這同時讓 AC 9（「已關閉」pill 僅出現於「我建立的」）自動成立：`all` 既然排除了
        視同關閉者，那個 pill 就不可能出現在該分頁。

        條件與 `rules.is_effectively_closed` 同義但寫成 SQL——該函式吃單列 Python 物件，
        這裡要能下推到 DB 做分頁。**兩處若要改，必須一起改。**

        ## 本查詢**只選 `EtCourse`**

        `paginate()` 取結果用 `result.scalars()`，**只會拿第一欄**——把聚合值塞進同一個
        select 會被靜默丟掉。章節數 / 學員數 / 標籤 / 建立者姓名改由 service 以該頁的
        `course_id` 批次補齊（見 `counts_by_course` 等），不是 N+1。
        """
        stmt = select(EtCourse).where(EtCourse.deleted == 0)

        if scope == "mine":
            stmt = stmt.where(EtCourse.owner_id == actor_id)
        else:
            stmt = stmt.where(
                EtCourse.status == COURSE_PUBLISHED,
                # 訖止為空＝沒有結束日，不因缺欄位關掉一門教師沒要求關閉的課
                # （與 `rules.is_effectively_closed` 的同一條判斷對齊）
                or_(EtCourse.open_end_at.is_(None), EtCourse.open_end_at >= now),
            )
            if owner_id:
                stmt = stmt.where(EtCourse.owner_id == owner_id)

        if keyword:
            # ⚠️ 必須跳脫——不跳脫時使用者輸入 `%` 會變成「列出全部」、`_` 變單字元萬用，
            # 而且**沒有任何錯誤訊息**。`like_escape` 模組的用法明訂要搭配具名的
            # `LIKE_ESCAPE_CHAR`，不要自己寫字面的反斜線。
            #
            # 用 `ilike` 而非 `like`：這是搜尋框，使用者不該因為大小寫打錯而找不到課程。
            stmt = stmt.where(EtCourse.course_name.ilike(like_contains(keyword), escape=LIKE_ESCAPE_CHAR))

        if tag_id is not None:
            # 一課程多標籤，任一命中即列出（`FR-ET-US7-02`）。用 EXISTS 而非 JOIN——
            # JOIN 會在課程掛多個標籤時產生重複列。
            #
            # **不濾 `EtTag.is_active`**：停用標籤仍須可用於篩選，否則掛著已停用標籤的
            # 歷史課程從此搜不到（`spec.md` §受訓單位標籤規則：停用僅影響新課程掛載）。
            stmt = stmt.where(
                select(EtCourseTag.course_tag_id)
                .where(
                    EtCourseTag.course_id == EtCourse.course_id,
                    EtCourseTag.tag_id == tag_id,
                    EtCourseTag.deleted == 0,
                )
                .correlate(EtCourse)
                .exists()
            )

        # 新的在前，與 ET04「我的課程」一致
        return stmt.order_by(EtCourse.created_date.desc(), EtCourse.course_id.desc())

    async def counts_by_course(self, db: AsyncSession, course_ids: list[int]) -> dict[int, tuple[int, int]]:
        """`{course_id: (章節數, 在籍學員數)}`——**兩次 grouped query，不是逐筆**。

        一頁十幾張卡，逐筆再查兩次就是幾十次往返。

        ⚠️ 學員數**必須同時濾 `IS_REMOVED` 與 `DELETED`**：兩者語意不同（見
        `learning/repository.is_enrolled`）。卡片上的數字問的是「現在有幾個人在上」，
        不是「歷來有幾個人加入過」。

        ⚠️ 兩個計數**不可合併成一次 JOIN**——兩個一對多關聯相乘會讓計數互相灌水
        （2 章節 × 3 學員 → 兩邊都變 6）。
        """
        if not course_ids:
            return {}
        chapters = dict(
            (
                await db.execute(
                    select(EtChapter.course_id, func.count())
                    .where(EtChapter.course_id.in_(course_ids), EtChapter.deleted == 0)
                    .group_by(EtChapter.course_id)
                )
            ).all()
        )
        students = dict(
            (
                await db.execute(
                    select(EtEnrollment.course_id, func.count())
                    .where(
                        EtEnrollment.course_id.in_(course_ids),
                        EtEnrollment.is_removed.is_(False),
                        EtEnrollment.deleted == 0,
                    )
                    .group_by(EtEnrollment.course_id)
                )
            ).all()
        )
        return {cid: (int(chapters.get(cid, 0)), int(students.get(cid, 0))) for cid in course_ids}

    async def tags_by_course(self, db: AsyncSession, course_ids: list[int]) -> dict[int, list[EtTag]]:
        """`{course_id: [EtTag, ...]}`——一次 JOIN 取回整頁的標籤。

        **不濾 `EtTag.is_active`**：課程既有已掛的停用標籤仍須顯示，否則卡片上的標籤
        會憑空少一個（`spec.md` §受訓單位標籤規則：停用僅影響新課程掛載）。
        """
        if not course_ids:
            return {}
        rows = (
            await db.execute(
                select(EtCourseTag.course_id, EtTag)
                .join(EtTag, EtTag.tag_id == EtCourseTag.tag_id)
                .where(
                    EtCourseTag.course_id.in_(course_ids),
                    EtCourseTag.deleted == 0,
                    EtTag.deleted == 0,
                )
                .order_by(EtCourseTag.course_id, EtTag.tag_name)
            )
        ).all()
        grouped: dict[int, list[EtTag]] = {cid: [] for cid in course_ids}
        for course_id, tag in rows:
            grouped[course_id].append(tag)
        return grouped

    async def list_all_tags(self, db: AsyncSession) -> list[EtTag]:
        """篩選下拉的標籤來源：**`ET_TAG` 全部（含停用者）**。

        ⚠️ 與同檔 `EtCourseTagRepository.list_options` **語意相反**，兩者不可互換：

        | 用途 | 來源 | 為何 |
        |---|---|---|
        | ET02 編輯時掛標籤 | 啟用中 + 該課程已掛之停用者 | 停用標籤不得**新掛**（FR-ET-US3-03）|
        | ET01 清單篩選（本函式）| **全部含停用** | 要查得到掛著已停用標籤的**歷史課程** |

        用錯會讓舊課程從此搜不到，而畫面上不會有任何異常。
        """
        rows = await db.scalars(select(EtTag).where(EtTag.deleted == 0).order_by(EtTag.tag_name))
        return list(rows)

    async def list_invitation_codes(self, db: AsyncSession) -> set[str]:
        """所有已使用之邀請碼（供產碼時判重）。

        **不濾 `DELETED = 0`**：邀請碼於 `ET_COURSE` 上是全域唯一約束
        （`UQ_ET_COURSE_INVITATION_CODE`，全表），軟刪除的課程仍佔著它的碼。只查未
        刪除的會讓產碼器以為某個碼可用，插入時才被約束擋下。

        > 一次撈成集合是 `generate_invitation_code` 的要求——它的 `exists` 為**同步**
        > callable，不能在裡面等待非同步查詢。
        """
        rows = await db.scalars(select(EtCourse.invitation_code).where(EtCourse.invitation_code.is_not(None)))
        return set(rows)

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

    async def resolve_owner(
        self, db: AsyncSession, *, material_id: int | None = None, quiz_id: int | None = None
    ) -> tuple[int, str] | None:
        """由教材 / 測驗反查其所屬課程，回 `(course_id, owner_id)`。

        單次 join 而非「教材 → 項目 → 章節 → 課程」四段查詢：擁有權判定在每個教材 /
        測驗端點都要做一次，四段查詢會讓每個請求多三個 round trip。

        回 `None` 的情形：教材 / 測驗不存在，或存在但沒有任何未刪除的項目指向它
        （孤兒）。呼叫端一律當成 404——孤兒教材在 UI 上無從到達，回 403 反而會洩漏
        「這筆資料存在但你沒權限」。
        """
        if material_id is not None:
            condition = EtItem.material_id == material_id
        elif quiz_id is not None:
            condition = EtItem.quiz_id == quiz_id
        else:
            return None
        row = await db.execute(
            select(EtCourse.course_id, EtCourse.owner_id)
            .join(EtChapter, EtChapter.course_id == EtCourse.course_id)
            .join(EtItem, EtItem.chapter_id == EtChapter.chapter_id)
            .where(condition, EtItem.deleted == 0, EtChapter.deleted == 0, EtCourse.deleted == 0)
            .limit(1)
        )
        found = row.first()
        return (found[0], found[1]) if found else None

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
