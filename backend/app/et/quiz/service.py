"""ET 測驗設定與題目 Service（US3 / #203）。

**稽核**：沿用課程之功能碼 `ET-COURSE`（`spec.md` §稽核來源功能碼明列其涵蓋課程下
章節、教材、**測驗**、問卷之編修與刪除），`target_id` 一律填課程 ID，使同一門課的
異動在稽核查詢上串得起來。

**授權**：測驗無自己的擁有者概念——回溯至所屬課程
（`EtItemRepository.resolve_owner` 單次 join）。找不到所屬課程者視為 404。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtItemRepository
from app.et.course.rules import ensure_owner
from app.et.quiz.repository import EtQuizRepository
from app.et.quiz.rules import (
    ensure_correct_options_valid,
    ensure_option_count_valid,
    ensure_question_reorder_complete,
    resequence_questions,
)
from app.et.quiz.schemas import (
    OptionRow,
    QuestionCreateReq,
    QuestionReorderReq,
    QuestionRow,
    QuestionUpdateReq,
    QuizDetail,
    QuizUpdateReq,
)
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此測驗", error_code="ET_QUIZ_001")
_QUESTION_NOT_FOUND = AppError(status_code=404, detail="查無此題目", error_code="ET_QUESTION_001")


class EtQuizService:
    """測驗設定、題目與選項之編修。"""

    def __init__(
        self,
        quizzes: EtQuizRepository | None = None,
        items: EtItemRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._quizzes = quizzes or EtQuizRepository()
        self._items = items or EtItemRepository()
        self._audit = audit or AuditLogService()

    async def get_detail(self, db: AsyncSession, quiz_id: int, *, actor_id: str) -> QuizDetail:
        """測驗詳細——設定、題目與選項一次帶齊，並附配分總和。"""
        quiz, _ = await self._require_owned(db, quiz_id, actor_id)
        questions = await self._quizzes.list_questions(db, quiz_id)
        options = await self._quizzes.list_options(db, [q.question_id for q in questions])

        by_question: dict[int, list[OptionRow]] = {}
        for option in options:
            by_question.setdefault(option.question_id, []).append(OptionRow.model_validate(option))

        return QuizDetail(
            quiz_id=quiz.quiz_id,
            quiz_name=quiz.quiz_name,
            description=quiz.description,
            pass_score=quiz.pass_score,
            time_limit_min=quiz.time_limit_min,
            max_retry=quiz.max_retry,
            version=quiz.version,
            questions=[
                QuestionRow(
                    question_id=q.question_id,
                    question_type=q.question_type,
                    stem=q.stem,
                    points=q.points,
                    sort_order=q.sort_order,
                    version=q.version,
                    options=by_question.get(q.question_id, []),
                )
                for q in questions
            ],
            # 由後端算：讓前端自行加總會在題目分頁載入時算錯。**不在此阻擋 ≠ 100**——
            # 逐題新增時總和必然一度不等於 100，阻擋發布是 #204 的事。
            points_total=sum(q.points for q in questions),
        )

    async def update_settings(
        self, db: AsyncSession, quiz_id: int, req: QuizUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新測驗設定（名稱、說明、及格分數、時間限制、重考上限）。

        `description` 為**純文字**（SA 裁示 #203 Q1），與教材說明文字分屬兩條路徑——
        **不經 HTML 消毒**，前端亦須以純文字渲染。
        """
        _, course_id = await self._require_owned(db, quiz_id, operator.user_id)
        rowcount = await self._quizzes.update_settings(
            db,
            quiz_id,
            req.version,
            name=req.quiz_name,
            description=req.description,
            pass_score=req.pass_score,
            time_limit_min=req.time_limit_min,
            max_retry=req.max_retry,
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_QUIZ")
        await self._log(db, "UPDATE", operator.user_id, course_id, "更新測驗設定")

    async def add_question(
        self, db: AsyncSession, quiz_id: int, req: QuestionCreateReq, *, operator: OperatorInfo
    ) -> QuestionRow:
        """新增題目（含其全部選項），追加至最末。"""
        _, course_id = await self._require_owned(db, quiz_id, operator.user_id)
        self._validate_options(req)
        question = await self._quizzes.add_question(
            db,
            quiz_id,
            question_type=req.question_type,
            stem=req.stem,
            points=req.points,
            options=[(o.option_text, o.is_correct) for o in req.options],
            operator=operator,
        )
        await self._log(db, "CREATE", operator.user_id, course_id, "新增測驗題目")
        return await self._question_row(db, question)

    async def update_question(
        self, db: AsyncSession, question_id: int, req: QuestionUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新題目與其選項（選項全量覆寫；帶題目自身之 `version`）。"""
        question = await self._quizzes.get_question(db, question_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        _, course_id = await self._require_owned(db, question.quiz_id, operator.user_id)
        self._validate_options(req)
        rowcount = await self._quizzes.replace_question(
            db,
            question_id,
            req.version,
            question_type=req.question_type,
            stem=req.stem,
            points=req.points,
            options=[(o.option_text, o.is_correct) for o in req.options],
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_QUESTION")
        await self._log(db, "UPDATE", operator.user_id, course_id, "更新測驗題目")

    async def delete_question(self, db: AsyncSession, question_id: int, *, operator: OperatorInfo) -> None:
        """刪除題目：本體、選項與學員作答明細皆軟刪，剩餘題目順序遞補。

        > 學員作答明細（`ET_QUIZ_ATTEMPT_D`）**亦連帶軟刪除**（2026-08-24 #202 裁示，
        > 原 spec 為 hard delete）。成績查詢務必排除 `DELETED = 1`，否則已刪題目的
        > 得分會被計入。作答**主檔**不刪——刪的是一題，不是整場作答。
        """
        question = await self._quizzes.get_question(db, question_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        _, course_id = await self._require_owned(db, question.quiz_id, operator.user_id)
        await self._quizzes.soft_delete_questions(db, [question_id], operator)
        await self._quizzes.resequence_questions(db, question.quiz_id, operator)
        await self._log(db, "DELETE", operator.user_id, course_id, "刪除測驗題目")

    async def reorder_questions(
        self, db: AsyncSession, quiz_id: int, req: QuestionReorderReq, *, operator: OperatorInfo
    ) -> None:
        """重排題目順序（送完整陣列；帶**測驗層** `version`）。

        這是教師端的呈現順序。學員作答時的順序由系統洗牌並凍結於 attempt 快照（#6），
        不依此欄位。
        """
        _, course_id = await self._require_owned(db, quiz_id, operator.user_id)
        current = await self._quizzes.list_questions(db, quiz_id)
        ensure_question_reorder_complete(current_ids={q.question_id for q in current}, requested=req.question_ids)
        rowcount = await self._quizzes.bump_version(db, quiz_id, req.version, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_QUIZ")
        await self._quizzes.apply_question_order(db, resequence_questions(req.question_ids), operator)
        await self._log(db, "UPDATE", operator.user_id, course_id, "調整測驗題目順序")

    # ── 內部 ────────────────────────────────────────────────────────────────

    def _validate_options(self, req: QuestionCreateReq) -> None:
        """選項數與正確選項數之業務規則。

        schema 的 `max_length` 只擋請求格式（多送幾個選項），這裡擋的是業務規則
        （少於 2 個、正確選項數不符題型）——兩者錯誤碼與訊息不同，教師才知道要改什麼。
        """
        ensure_option_count_valid(len(req.options))
        ensure_correct_options_valid(req.question_type, correct_count=sum(1 for o in req.options if o.is_correct))

    async def _require_owned(self, db: AsyncSession, quiz_id: int, actor_id: str):
        quiz = await self._quizzes.get(db, quiz_id)
        if quiz is None:
            raise _NOT_FOUND
        resolved = await self._items.resolve_owner(db, quiz_id=quiz_id)
        if resolved is None:
            raise _NOT_FOUND  # 孤兒測驗：UI 無從到達，不揭露其存在
        course_id, owner_id = resolved
        ensure_owner(owner_id=owner_id, actor_id=actor_id)
        return quiz, course_id

    async def _question_row(self, db: AsyncSession, question) -> QuestionRow:
        options = await self._quizzes.list_options(db, [question.question_id])
        return QuestionRow(
            question_id=question.question_id,
            question_type=question.question_type,
            stem=question.stem,
            points=question.points,
            sort_order=question.sort_order,
            version=question.version,
            options=[OptionRow.model_validate(o) for o in options],
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
