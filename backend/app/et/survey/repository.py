"""ET 課後問卷 Repository（ET_SURVEY / ET_SURVEY_QUESTION / ET_SURVEY_OPTION；US3 / #204）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。更新型方法回傳受影響列數供 service 交給
`ensure_version_matched()` 判定樂觀鎖。

**沒有刪除問卷的方法**——SA 裁示（#204 Q1 → B）問卷只能停用。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.progress.models import EtEnrollment
from app.et.survey.models import EtSurvey, EtSurveyOption, EtSurveyQuestion, EtSurveyResponseM


class EtSurveyRepository:
    """`ET_SURVEY` 及其題目 / 選項之存取。"""

    async def get_by_course(self, db: AsyncSession, course_id: int) -> EtSurvey | None:
        return await db.scalar(select(EtSurvey).where(EtSurvey.course_id == course_id, EtSurvey.deleted == 0))

    async def get(self, db: AsyncSession, survey_id: int) -> EtSurvey | None:
        return await db.scalar(select(EtSurvey).where(EtSurvey.survey_id == survey_id, EtSurvey.deleted == 0))

    async def create(self, db: AsyncSession, course_id: int, name: str, operator: OperatorInfo) -> EtSurvey:
        """建立問卷（無題目）。`IS_ACTIVE` 預設 true（data-model §ET_SURVEY）。"""
        survey = EtSurvey(
            course_id=course_id,
            survey_name=name,
            is_active=True,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(survey)
        await db.flush()
        return survey

    async def update_basic(
        self, db: AsyncSession, survey_id: int, version: int, *, name: str, is_active: bool, operator: OperatorInfo
    ) -> int:
        """更新問卷名稱與啟用狀態並遞增 `VERSION`；回傳受影響列數供樂觀鎖判定。"""
        result = await db.execute(
            update(EtSurvey)
            .where(EtSurvey.survey_id == survey_id, EtSurvey.deleted == 0, EtSurvey.version == version)
            .values(
                survey_name=name,
                is_active=is_active,
                version=EtSurvey.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, survey_id: int, version: int, operator: OperatorInfo) -> int:
        """僅遞增問卷 `VERSION`（供題目重排之樂觀鎖）；回傳受影響列數。"""
        result = await db.execute(
            update(EtSurvey)
            .where(EtSurvey.survey_id == survey_id, EtSurvey.deleted == 0, EtSurvey.version == version)
            .values(version=EtSurvey.version + 1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()
        return result.rowcount

    # ── 填答統計 ────────────────────────────────────────────────────────────

    async def has_responses(self, db: AsyncSession, survey_id: int) -> bool:
        """是否存在任何**未刪除**之填答——凍結判定（AC 21）。

        用 `EXISTS` 語意（`LIMIT 1`）而非 `COUNT`：凍結只在乎有沒有、不在乎幾筆，
        找到第一筆就能停。
        """
        found = await db.scalar(
            select(EtSurveyResponseM.response_id)
            .where(EtSurveyResponseM.survey_id == survey_id, EtSurveyResponseM.deleted == 0)
            .limit(1)
        )
        return found is not None

    async def count_responses(self, db: AsyncSession, survey_id: int) -> int:
        """已填人數（供問卷卡片顯示「已填 N / 未填 M」）。"""
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtSurveyResponseM)
                .where(EtSurveyResponseM.survey_id == survey_id, EtSurveyResponseM.deleted == 0)
            )
            or 0
        )

    async def count_enrollments(self, db: AsyncSession, course_id: int) -> int:
        """該課程已加入之學員數（供計算未填人數）。

        > 學員加入課程屬 `ET-4` / `ET-8`，本 issue 只讀不寫。目前尚無人能加入，
        > 故實際會是 0——這是預期值，不是查詢寫錯。
        """
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtEnrollment)
                .where(EtEnrollment.course_id == course_id, EtEnrollment.deleted == 0)
            )
            or 0
        )

    # ── 題目與選項 ──────────────────────────────────────────────────────────

    async def list_questions(self, db: AsyncSession, survey_id: int) -> list[EtSurveyQuestion]:
        rows = await db.scalars(
            select(EtSurveyQuestion)
            .where(EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0)
            .order_by(EtSurveyQuestion.sort_order, EtSurveyQuestion.sq_id)
        )
        return list(rows)

    async def list_options(self, db: AsyncSession, sq_ids: list[int]) -> list[EtSurveyOption]:
        """批次取多題之選項——避免逐題查詢造成 N+1。"""
        if not sq_ids:
            return []
        rows = await db.scalars(
            select(EtSurveyOption)
            .where(EtSurveyOption.sq_id.in_(sq_ids), EtSurveyOption.deleted == 0)
            .order_by(EtSurveyOption.sq_id, EtSurveyOption.sort_order, EtSurveyOption.so_id)
        )
        return list(rows)

    async def get_question(self, db: AsyncSession, sq_id: int) -> EtSurveyQuestion | None:
        return await db.scalar(
            select(EtSurveyQuestion).where(EtSurveyQuestion.sq_id == sq_id, EtSurveyQuestion.deleted == 0)
        )

    async def next_question_order(self, db: AsyncSession, survey_id: int) -> int:
        max_order = await db.scalar(
            select(func.max(EtSurveyQuestion.sort_order)).where(
                EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0
            )
        )
        return (max_order or 0) + 1

    async def add_question(
        self, db: AsyncSession, survey_id: int, *, stem: str, options: list[str], operator: OperatorInfo
    ) -> EtSurveyQuestion:
        """新增題目與其全部選項，追加至問卷最末。"""
        question = EtSurveyQuestion(
            survey_id=survey_id,
            stem=stem,
            sort_order=await self.next_question_order(db, survey_id),
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(question)
        await db.flush()
        await self._insert_options(db, question.sq_id, options, operator)
        return question

    async def replace_question(
        self, db: AsyncSession, sq_id: int, version: int, *, stem: str, options: list[str], operator: OperatorInfo
    ) -> int:
        """更新題目本體並**全量覆寫**其選項；回傳題目更新之受影響列數。

        **先更題目再換選項**：題目更新帶樂觀鎖，版本不符時 rowcount 為 0，此時不該
        已經把選項換掉。呼叫端據 rowcount 判定並讓交易回滾。

        > 舊選項軟刪、新選項自 1 起插入——這正是 `UX_ET_SURVEY_OPTION_ORDER` 必須是
        > **部分**唯一索引的原因（migration `e9ec96adabab`）。全表唯一時舊列會繼續
        > 佔著 `SORT_ORDER=1`，第一個新選項就插不進去。
        """
        result = await db.execute(
            update(EtSurveyQuestion)
            .where(
                EtSurveyQuestion.sq_id == sq_id,
                EtSurveyQuestion.deleted == 0,
                EtSurveyQuestion.version == version,
            )
            .values(
                stem=stem,
                version=EtSurveyQuestion.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        if result.rowcount:
            await db.execute(
                update(EtSurveyOption)
                .where(EtSurveyOption.sq_id == sq_id, EtSurveyOption.deleted == 0)
                .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
            )
            await self._insert_options(db, sq_id, options, operator)
        return result.rowcount

    async def soft_delete_question(self, db: AsyncSession, sq_id: int, operator: OperatorInfo) -> None:
        """軟刪除題目與其選項。

        **填答明細（`ET_SURVEY_RESPONSE_D`）不處理**——刪題只可能發生在尚無填答時
        （`ensure_editable` 已擋），故不存在需要連帶處理的填答資料。這與測驗題目
        不同：測驗題目可在有作答後刪除，因此需連帶軟刪 `ET_QUIZ_ATTEMPT_D`。
        """
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": utcnow()}
        await db.execute(
            update(EtSurveyOption).where(EtSurveyOption.sq_id == sq_id, EtSurveyOption.deleted == 0).values(**audit)
        )
        await db.execute(
            update(EtSurveyQuestion)
            .where(EtSurveyQuestion.sq_id == sq_id, EtSurveyQuestion.deleted == 0)
            .values(**audit)
        )
        await db.flush()

    async def apply_question_order(self, db: AsyncSession, order_map: dict[int, int], operator: OperatorInfo) -> None:
        """依 `{sq_id: sort_order}` 批次更新順序（**兩階段寫入**）。

        ## 為何要兩階段（與測驗題目不同，不可照抄 `EtQuizRepository`）

        `UX_ET_SURVEY_QUESTION_ORDER` 為 `(SURVEY_ID, SORT_ORDER)` 唯一索引，而
        `ET_QUESTION` 之 `SORT_ORDER` **沒有**唯一約束。交換相鄰兩題時若逐列直接
        寫入，第一列寫成 2 的瞬間會與尚未更新的第二列重複，PostgreSQL 立即拋
        `UniqueViolationError`——非 deferrable 之唯一索引是逐列即時檢核，而部分索引
        （`WHERE DELETED = 0`）無法宣告 deferrable。

        故先把所有涉及之列移到**負數暫存區**（以目標順序取負，因目標順序本身唯一，
        負值亦唯一且不與任何正值業務資料衝突），再一次落定為正值。兩階段皆在同一
        交易內，外部看不到中間狀態。比照 `EtChapterRepository.apply_order`（#202）。

        亦不遞增題目自身 `VERSION`：順序屬問卷結構，遞增會讓正在編輯該題的另一裝置
        無故衝突。
        """
        if not order_map:
            return
        now = utcnow()
        for phase_value in (lambda target: -target, lambda target: target):
            for sq_id, sort_order in order_map.items():
                await db.execute(
                    update(EtSurveyQuestion)
                    .where(EtSurveyQuestion.sq_id == sq_id, EtSurveyQuestion.deleted == 0)
                    .values(
                        sort_order=phase_value(sort_order),
                        updated_user=operator.user_id,
                        updated_date=now,
                    )
                )
        await db.flush()

    async def resequence_questions(self, db: AsyncSession, survey_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘題目之 `SORT_ORDER` 重編為 1..N。"""
        remaining = await self.list_questions(db, survey_id)
        await self.apply_question_order(db, {q.sq_id: i for i, q in enumerate(remaining, start=1)}, operator)

    async def _insert_options(self, db: AsyncSession, sq_id: int, options: list[str], operator: OperatorInfo) -> None:
        now = utcnow()
        for index, text in enumerate(options, start=1):
            db.add(
                EtSurveyOption(
                    sq_id=sq_id,
                    option_text=text,
                    sort_order=index,
                    created_user=operator.user_id,
                    created_date=now,
                )
            )
        await db.flush()
