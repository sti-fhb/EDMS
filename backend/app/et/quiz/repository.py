"""ET 測驗 Repository（ET_QUIZ / ET_QUESTION / ET_OPTION；US3 / #203）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。更新型方法回傳受影響列數供 service 交給
`ensure_version_matched()` 判定樂觀鎖。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM

#: 測驗設定之預設值（data-model §ET_QUIZ）。
DEFAULT_PASS_SCORE = 80
DEFAULT_MAX_RETRY = 3


class EtQuizRepository:
    """`ET_QUIZ` 及其題目 / 選項之存取。"""

    async def create_shell(self, db: AsyncSession, name: str, operator: OperatorInfo) -> EtQuiz:
        """建立空殼測驗（無題目、採預設設定值）。

        與 `ET_ITEM` 於同一交易建立。「每測驗至少 1 題」之檢核在**儲存測驗**時才套用，
        不在建立時。
        """
        quiz = EtQuiz(
            quiz_name=name,
            pass_score=DEFAULT_PASS_SCORE,
            max_retry=DEFAULT_MAX_RETRY,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(quiz)
        await db.flush()
        return quiz

    async def get(self, db: AsyncSession, quiz_id: int) -> EtQuiz | None:
        return await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0))

    async def list_questions(self, db: AsyncSession, quiz_id: int) -> list[EtQuestion]:
        """依 `SORT_ORDER` 列出測驗之題目（教師端順序；學員端洗牌不依此）。"""
        rows = await db.scalars(
            select(EtQuestion)
            .where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0)
            .order_by(EtQuestion.sort_order, EtQuestion.question_id)
        )
        return list(rows)

    async def list_options(self, db: AsyncSession, question_ids: list[int]) -> list[EtOption]:
        """批次取多題之選項——避免逐題查詢造成 N+1。"""
        if not question_ids:
            return []
        rows = await db.scalars(
            select(EtOption)
            .where(EtOption.question_id.in_(question_ids), EtOption.deleted == 0)
            .order_by(EtOption.question_id, EtOption.sort_order, EtOption.option_id)
        )
        return list(rows)

    async def next_question_order(self, db: AsyncSession, quiz_id: int) -> int:
        max_order = await db.scalar(
            select(func.max(EtQuestion.sort_order)).where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0)
        )
        return (max_order or 0) + 1

    async def update_settings(
        self,
        db: AsyncSession,
        quiz_id: int,
        version: int,
        *,
        name: str,
        description: str | None,
        pass_score: int,
        time_limit_min: int | None,
        max_retry: int,
        operator: OperatorInfo,
    ) -> int:
        """更新測驗設定並遞增 `VERSION`；回傳受影響列數供樂觀鎖判定。"""
        result = await db.execute(
            update(EtQuiz)
            .where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0, EtQuiz.version == version)
            .values(
                quiz_name=name,
                description=description,
                pass_score=pass_score,
                time_limit_min=time_limit_min,
                max_retry=max_retry,
                version=EtQuiz.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, quiz_id: int, version: int, operator: OperatorInfo) -> int:
        """僅遞增測驗 `VERSION`（供題目重排之樂觀鎖）；回傳受影響列數。"""
        result = await db.execute(
            update(EtQuiz)
            .where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0, EtQuiz.version == version)
            .values(version=EtQuiz.version + 1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()
        return result.rowcount

    async def get_question(self, db: AsyncSession, question_id: int) -> EtQuestion | None:
        return await db.scalar(select(EtQuestion).where(EtQuestion.question_id == question_id, EtQuestion.deleted == 0))

    async def add_question(
        self,
        db: AsyncSession,
        quiz_id: int,
        *,
        question_type: str,
        stem: str,
        points: int,
        options: list[tuple[str, bool]],
        operator: OperatorInfo,
    ) -> EtQuestion:
        """新增題目與其全部選項，追加至測驗最末。

        選項順序即傳入陣列的順序。這是**教師端**順序；學員作答時的選項順序由系統
        洗牌並凍結於 attempt 快照（data-model §ET_OPTION：「學員端洗牌不依此」）。
        """
        now = utcnow()
        question = EtQuestion(
            quiz_id=quiz_id,
            question_type=question_type,
            stem=stem,
            points=points,
            sort_order=await self.next_question_order(db, quiz_id),
            version=0,
            created_user=operator.user_id,
            created_date=now,
        )
        db.add(question)
        await db.flush()
        await self._insert_options(db, question.question_id, options, operator)
        return question

    async def replace_question(
        self,
        db: AsyncSession,
        question_id: int,
        version: int,
        *,
        question_type: str,
        stem: str,
        points: int,
        options: list[tuple[str, bool]],
        operator: OperatorInfo,
    ) -> int:
        """更新題目本體並**全量覆寫**其選項；回傳題目更新之受影響列數。

        選項全量覆寫（舊的軟刪、新的插入）而非逐項 diff：選項無獨立識別需求——
        作答紀錄以 snapshot 保存當時的選項內容，不以 `OPTION_ID` 外鍵關聯，
        故換一批選項不會讓歷史作答失去意義。

        **先更題目再換選項**：題目更新帶樂觀鎖，版本不符時 rowcount 為 0，此時不該
        已經把選項換掉。呼叫端據 rowcount 判定並讓交易回滾。
        """
        result = await db.execute(
            update(EtQuestion)
            .where(
                EtQuestion.question_id == question_id,
                EtQuestion.deleted == 0,
                EtQuestion.version == version,
            )
            .values(
                question_type=question_type,
                stem=stem,
                points=points,
                version=EtQuestion.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        if result.rowcount:
            await db.execute(
                update(EtOption)
                .where(EtOption.question_id == question_id, EtOption.deleted == 0)
                .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
            )
            await self._insert_options(db, question_id, options, operator)
        return result.rowcount

    async def apply_question_order(self, db: AsyncSession, order_map: dict[int, int], operator: OperatorInfo) -> None:
        """依 `{question_id: sort_order}` 批次更新順序。

        **不需兩階段寫入**——`ET_QUESTION` 之 `SORT_ORDER` 沒有唯一約束（僅一般索引
        `IX_ET_QUESTION_QUIZ`），data-model 亦未要求其唯一，故中途出現重複值無妨。
        章節 / 項目 / 影片才需要負數暫存區。

        亦不遞增題目自身 `VERSION`：順序屬測驗結構，遞增會讓正在編輯該題的另一裝置
        無故衝突。
        """
        if not order_map:
            return
        now = utcnow()
        for question_id, sort_order in order_map.items():
            await db.execute(
                update(EtQuestion)
                .where(EtQuestion.question_id == question_id, EtQuestion.deleted == 0)
                .values(sort_order=sort_order, updated_user=operator.user_id, updated_date=now)
            )
        await db.flush()

    async def resequence_questions(self, db: AsyncSession, quiz_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘題目之 `SORT_ORDER` 重編為 1..N。"""
        remaining = await self.list_questions(db, quiz_id)
        await self.apply_question_order(db, {q.question_id: i for i, q in enumerate(remaining, start=1)}, operator)

    async def _insert_options(
        self, db: AsyncSession, question_id: int, options: list[tuple[str, bool]], operator: OperatorInfo
    ) -> None:
        now = utcnow()
        for index, (text, is_correct) in enumerate(options, start=1):
            db.add(
                EtOption(
                    question_id=question_id,
                    option_text=text,
                    is_correct=is_correct,
                    sort_order=index,
                    created_user=operator.user_id,
                    created_date=now,
                )
            )
        await db.flush()

    async def soft_delete_questions(self, db: AsyncSession, question_ids: list[int], operator: OperatorInfo) -> None:
        """軟刪除題目、其選項，及學員於該題之作答明細。

        > `ET_QUIZ_ATTEMPT_D` **亦連帶軟刪除**（2026-08-24 #202 裁示，原 spec 為 hard
        > delete）。成績查詢務必排除 `DELETED = 1`，否則已刪題目的得分會被計入。

        `ET_QUIZ_ATTEMPT_M`（作答主檔）**不刪**——刪的是題目、不是整場作答；該場作答
        仍存在，只是少了這一題。整場作廢是刪除測驗時的事（見 `soft_delete_cascade`）。
        """
        if not question_ids:
            return
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": utcnow()}
        await db.execute(
            update(EtOption).where(EtOption.question_id.in_(question_ids), EtOption.deleted == 0).values(**audit)
        )
        await db.execute(
            update(EtQuizAttemptD)
            .where(EtQuizAttemptD.question_id.in_(question_ids), EtQuizAttemptD.deleted == 0)
            .values(**audit)
        )
        await db.execute(
            update(EtQuestion).where(EtQuestion.question_id.in_(question_ids), EtQuestion.deleted == 0).values(**audit)
        )
        await db.flush()

    async def soft_delete_cascade(self, db: AsyncSession, quiz_ids: list[int], operator: OperatorInfo) -> None:
        """軟刪除測驗本體與其題目、選項，及學員之整場作答紀錄。

        連帶範圍（**全部軟刪除**）：

        1. `ET_QUESTION` / `ET_OPTION` — 測驗之題目與選項
        2. `ET_QUIZ_ATTEMPT_M` / `ET_QUIZ_ATTEMPT_D` — 學員之作答主檔與明細

        與 `soft_delete_questions` 的差別：那裡只刪單題（作答主檔保留），這裡整份測驗
        消失，該測驗的所有作答自然一併作廢。
        """
        if not quiz_ids:
            return
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": utcnow()}

        question_ids = list(
            await db.scalars(
                select(EtQuestion.question_id).where(EtQuestion.quiz_id.in_(quiz_ids), EtQuestion.deleted == 0)
            )
        )
        if question_ids:
            await db.execute(
                update(EtOption).where(EtOption.question_id.in_(question_ids), EtOption.deleted == 0).values(**audit)
            )
            await db.execute(update(EtQuestion).where(EtQuestion.question_id.in_(question_ids)).values(**audit))

        attempt_ids = list(
            await db.scalars(
                select(EtQuizAttemptM.attempt_id).where(
                    EtQuizAttemptM.quiz_id.in_(quiz_ids), EtQuizAttemptM.deleted == 0
                )
            )
        )
        if attempt_ids:
            await db.execute(
                update(EtQuizAttemptD)
                .where(EtQuizAttemptD.attempt_id.in_(attempt_ids), EtQuizAttemptD.deleted == 0)
                .values(**audit)
            )
            await db.execute(update(EtQuizAttemptM).where(EtQuizAttemptM.attempt_id.in_(attempt_ids)).values(**audit))

        await db.execute(update(EtQuiz).where(EtQuiz.quiz_id.in_(quiz_ids), EtQuiz.deleted == 0).values(**audit))
        await db.flush()
