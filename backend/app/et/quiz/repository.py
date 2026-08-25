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
