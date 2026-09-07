"""ET06 測驗作答 Service（US6 / #279）。

## 存取的四道守門

```
1. 反查鏈：quiz → item → chapter → course     → 任一跳斷掉 → 404
2. 授權：在籍 OR 擁有者                        → 兩者皆非 → 404
3. 解鎖：該測驗項目尚未解鎖                    → 404（僅「開始作答」時檢查）
4. 次數：本輪已用作答次數 > MAX_RETRY          → 409 ET_ATTEMPT_002
```

**守門 3 只掛在「開始作答」**：一旦 attempt 建立，它就是既成事實——中途因為教師調整
章節順序而讓學員無法提交已經寫好的考卷，比放行更糟。

**404 而非 403**：以 id 定址的資源回 403 等於確認「這個 quiz_id 存在，只是你不能看」，
可用來枚舉全站有多少測驗。比照 `ET_LEARN_001` / `ET_ENROLL_001` 的同一判斷。

## 兩條 #279 SA 裁示

| 裁示 | 執行點 |
|---|---|
| Q1 = A：進行中的 attempt **續作**而非作廢 | `start()` 先找 `IN_PROGRESS` |
| Q2 = C：刪題不連帶軟刪明細 | 於 `quiz/repository` 移除連帶，本模組因此可正常讀回明細 |

## 閱卷只讀快照

`_grade()` 的輸入全部來自 `ET_QUIZ_ATTEMPT_D` 的四個 `*_SNAPSHOT` 欄位。**不可**回頭查
`ET_QUESTION` / `ET_OPTION`——教師在學員作答期間改了配分或正確答案時，回查會靜默改變
計分結果，而學員拿到的是一個看起來正常的分數（`spec_us6` 場景 26）。
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.attempt.repository import EtAttemptRepository, parse_options_snapshot, parse_selected
from app.et.attempt.rules import (
    can_start_attempt,
    is_timed_out,
    remaining_attempts,
    remaining_seconds,
    score_question,
    shuffled,
)
from app.et.attempt.schemas import (
    AnswerReq,
    AttemptResult,
    AttemptState,
    OptionForAnswering,
    OptionResult,
    QuestionForAnswering,
    QuestionResult,
    QuizIntro,
)
from app.et.constants import ATTEMPT_SUBMITTED, ATTEMPT_TIMEOUT, QUESTION_MULTIPLE
from app.et.learning.repository import EtLearningRepository
from app.et.learning.rules import ensure_can_access
from app.et.progress.repository import EtProgressRepository
from app.et.progress.service import EtProgressService

_NOT_FOUND = AppError(status_code=404, detail="查無此測驗", error_code="ET_ATTEMPT_001")
_NO_ATTEMPTS = AppError(status_code=409, detail="重考次數已用完，請聯繫教師重置", error_code="ET_ATTEMPT_002")
_ALREADY_SUBMITTED = AppError(status_code=409, detail="此作答已提交，無法變更", error_code="ET_ATTEMPT_003")
_BAD_ANSWER = AppError(status_code=422, detail="作答資料無效", error_code="ET_ATTEMPT_004")

#: 明細的結果三態（前端據此上色；**由後端判定**）。
OUTCOME_CORRECT = "CORRECT"
OUTCOME_PARTIAL = "PARTIAL"
OUTCOME_WRONG = "WRONG"


class EtAttemptService:
    """學員端測驗：引導頁、開始作答、暫存、提交與自動閱卷。"""

    def __init__(
        self,
        repository: EtAttemptRepository | None = None,
        learning: EtLearningRepository | None = None,
        progress: EtProgressRepository | None = None,
        progress_service: EtProgressService | None = None,
    ) -> None:
        self._repo = repository or EtAttemptRepository()
        # 授權沿用 `learning` 的既有查詢——複製一份會讓「在籍」的定義有兩個版本
        self._learning = learning or EtLearningRepository()
        self._progress = progress or EtProgressRepository()
        self._progress_service = progress_service or EtProgressService()

    # ── 引導頁 ──────────────────────────────────────────────────────────────

    async def intro(self, db: AsyncSession, quiz_id: int, *, user_id: str) -> QuizIntro:
        """引導頁資訊（AC 1 / AC 2）。"""
        quiz, _item_id, _course_id = await self._require_access(db, quiz_id, user_id)
        total = await self._repo.attempt_total(db, user_id=user_id, quiz_id=quiz_id)
        base = await self._repo.reset_base(db, user_id=user_id, quiz_id=quiz_id)
        last, best, passed = await self._repo.score_summary(db, user_id=user_id, quiz_id=quiz_id)
        in_progress = await self._repo.find_in_progress(db, user_id=user_id, quiz_id=quiz_id)
        questions = await self._repo.list_questions(db, quiz_id)
        return QuizIntro(
            quiz_id=quiz.quiz_id,
            quiz_name=quiz.quiz_name,
            description=quiz.description,
            question_count=len(questions),
            pass_score=quiz.pass_score,
            time_limit_min=quiz.time_limit_min,
            max_retry=quiz.max_retry,
            remaining_attempts=remaining_attempts(total=total, reset_base=base, max_retry=quiz.max_retry),
            # 有未完成的作答時恆可進入——那是「繼續」而不是「開始」，不受次數限制
            can_start=in_progress is not None
            or can_start_attempt(total=total, reset_base=base, max_retry=quiz.max_retry),
            last_score=last,
            best_score=best,
            is_passed=passed,
            in_progress_attempt_id=in_progress.attempt_id if in_progress else None,
        )

    # ── 開始 / 續作 ─────────────────────────────────────────────────────────

    async def start(self, db: AsyncSession, quiz_id: int, *, operator: OperatorInfo) -> AttemptState:
        """開始作答；已有未完成者**回既有那一筆**（SA 裁示 Q1 = A）。

        續作不消耗次數、不重新洗牌、不重設計時——`ATTEMPT_NO` 早在第一次點「開始作答」
        時就配發，而剩餘時間一律由 `STARTED_AT` 推導。

        Raises:
            AppError: 404 查無 / 無權 / 項目未解鎖；409 `ET_ATTEMPT_002` 次數用完。
        """
        user_id = operator.user_id
        quiz, item_id, course_id = await self._require_access(db, quiz_id, user_id)

        existing = await self._repo.find_in_progress(db, user_id=user_id, quiz_id=quiz_id)
        if existing is not None:
            return await self._state(db, existing, quiz_name=quiz.quiz_name, resumed=True)

        # 解鎖只在「開始」時檢查——見模組 docstring
        if await self._progress_service.is_item_locked(db, course_id=course_id, user_id=user_id, item_id=item_id):
            raise _NOT_FOUND
        total = await self._repo.attempt_total(db, user_id=user_id, quiz_id=quiz_id)
        base = await self._repo.reset_base(db, user_id=user_id, quiz_id=quiz_id)
        if not can_start_attempt(total=total, reset_base=base, max_retry=quiz.max_retry):
            raise _NO_ATTEMPTS

        questions = await self._repo.list_questions(db, quiz_id)
        if not questions:
            # 沒有題目的測驗開不起來——建立一個零題的 attempt 會直接吃掉一次作答次數
            raise _NOT_FOUND
        options = await self._repo.options_by_question(db, [q.question_id for q in questions])
        attempt = await self._repo.create_attempt(
            db,
            user_id=user_id,
            course_id=course_id,
            quiz=quiz,
            attempt_no=total + 1,
            question_order=shuffled([q.question_id for q in questions]),
            option_order={q.question_id: shuffled([o.option_id for o in options[q.question_id]]) for q in questions},
            questions=questions,
            options_by_question=options,
            operator=operator,
        )
        return await self._state(db, attempt, quiz_name=quiz.quiz_name, resumed=False)

    async def state(self, db: AsyncSession, attempt_id: int, *, user_id: str) -> AttemptState:
        """取作答狀態（跳題 / 重新整理後回來）。"""
        attempt = await self._require_own_attempt(db, attempt_id, user_id)
        quiz = await self._repo.get_quiz(db, attempt.quiz_id)
        return await self._state(db, attempt, quiz_name=quiz.quiz_name if quiz else "", resumed=True)

    # ── 暫存 ────────────────────────────────────────────────────────────────

    async def save_answer(
        self, db: AsyncSession, attempt_id: int, question_id: int, req: AnswerReq, *, operator: OperatorInfo
    ) -> None:
        """暫存單題作答（AC 5）。

        **不擋逾時**：學員的網路慢了幾秒不該讓他剛選的答案消失，而逾時的效果由提交時的
        `TIMEOUT` 判定統一處理——時間到之後暫存的答案本來就進不了那次閱卷之外的地方。
        """
        attempt = await self._require_own_attempt(db, attempt_id, operator.user_id)
        self._ensure_in_progress(attempt)
        ok = await self._repo.save_answer(
            db,
            attempt_id=attempt_id,
            question_id=question_id,
            selected=req.selected_options,
            operator=operator,
        )
        if not ok:
            # 該題不屬於這次 attempt——可能是前端送錯，也可能是有人拿別人的 question_id
            raise _BAD_ANSWER

    # ── 提交與閱卷 ──────────────────────────────────────────────────────────

    async def submit(self, db: AsyncSession, attempt_id: int, *, operator: OperatorInfo) -> AttemptResult:
        """提交並即時自動閱卷（AC 7～11）。

        逾時**不拒收**——`spec_us6` 場景 10 要求「以當前作答狀態自動提交」，故記為
        `TIMEOUT` 但照常計分。拒收等於沒收學員已經寫好的考卷。
        """
        attempt = await self._require_own_attempt(db, attempt_id, operator.user_id)
        self._ensure_in_progress(attempt)

        now = utcnow()
        details = await self._repo.list_details(db, attempt_id)
        per_question: dict[int, Decimal] = {}
        for detail in details:
            per_question[detail.question_id] = score_question(
                detail.type_snapshot,
                parse_selected(detail.selected_options),
                parse_options_snapshot(detail.options_snapshot),
                points=detail.points_snapshot,
            )
        total = sum(per_question.values(), Decimal(0))
        is_pass = total >= attempt.pass_score_snapshot
        timed_out = is_timed_out(started_at=attempt.started_at, time_limit_min=attempt.time_limit_snapshot, now=now)
        await self._repo.submit(
            db,
            attempt=attempt,
            status=ATTEMPT_TIMEOUT if timed_out else ATTEMPT_SUBMITTED,
            total=total,
            is_pass=is_pass,
            per_question=per_question,
            submitted_at=now,
            operator=operator,
        )

        if is_pass:
            await self._mark_item_completed(db, attempt=attempt, operator=operator)

        quiz = await self._repo.get_quiz(db, attempt.quiz_id)
        max_retry = quiz.max_retry if quiz else 0
        used_total = await self._repo.attempt_total(db, user_id=operator.user_id, quiz_id=attempt.quiz_id)
        base = await self._repo.reset_base(db, user_id=operator.user_id, quiz_id=attempt.quiz_id)
        return AttemptResult(
            attempt_id=attempt.attempt_id,
            attempt_no=attempt.attempt_no,
            status=attempt.status,
            score=total,
            pass_score=attempt.pass_score_snapshot,
            is_pass=is_pass,
            submitted_at=now,
            remaining_attempts=remaining_attempts(total=used_total, reset_base=base, max_retry=max_retry),
            questions=[
                _to_result(detail, per_question[detail.question_id])
                for detail in _in_snapshot_order(details, attempt.question_order)
            ],
        )

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_access(self, db: AsyncSession, quiz_id: int, user_id: str):
        """守門 1 + 2：反查鏈與「在籍 OR 擁有者」。"""
        quiz = await self._repo.get_quiz(db, quiz_id)
        context = await self._repo.quiz_context(db, quiz_id)
        if quiz is None or context is None:
            raise _NOT_FOUND
        item_id, course_id = context
        course = await self._learning.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        enrolled = await self._learning.is_enrolled(db, user_id=user_id, course_id=course_id)
        try:
            ensure_can_access(enrolled=enrolled, is_owner=course.owner_id == user_id)
        except AppError:
            raise _NOT_FOUND from None
        return quiz, item_id, course_id

    async def _require_own_attempt(self, db: AsyncSession, attempt_id: int, user_id: str):
        """只有 attempt 的**本人**能讀寫它。

        以 `USER_ID` 比對而非重跑課程授權：課程層的資格會變（被移除、課程關閉），但
        「這是誰的考卷」不會。用課程資格判定會讓學員被移除後連自己的歷史都讀不到。
        """
        attempt = await self._repo.get_attempt(db, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            raise _NOT_FOUND
        return attempt

    @staticmethod
    def _ensure_in_progress(attempt) -> None:
        if attempt.status != "IN_PROGRESS":
            raise _ALREADY_SUBMITTED

    async def _mark_item_completed(self, db: AsyncSession, *, attempt, operator: OperatorInfo) -> None:
        """及格 → 回寫項目層完成（AC 12），下一項 / 下一章隨之解鎖。

        ⚠️ **直接呼叫 repository，不繞經 `EtProgressService`**：那支的 `_guard_write`
        對 `COURSE_CLOSED` 一律 409，而「課程關閉當下已在作答的 attempt 仍可完成並計分」
        是 `spec_us6` 場景 27 明訂的行為（屬 #280 的範圍，本 issue 先不讓守門擋住它）。
        """
        context = await self._repo.quiz_context(db, attempt.quiz_id)
        if context is None:
            return
        item_id, course_id = context
        await self._progress.set_item_completed(
            db,
            user_id=attempt.user_id,
            course_id=course_id,
            item_id=item_id,
            completed=True,
            operator=operator,
        )

    async def _state(self, db: AsyncSession, attempt, *, quiz_name: str, resumed: bool) -> AttemptState:
        details = await self._repo.list_details(db, attempt.attempt_id)
        return AttemptState(
            attempt_id=attempt.attempt_id,
            quiz_id=attempt.quiz_id,
            quiz_name=quiz_name,
            attempt_no=attempt.attempt_no,
            pass_score=attempt.pass_score_snapshot,
            time_limit_min=attempt.time_limit_snapshot,
            remaining_sec=remaining_seconds(
                started_at=attempt.started_at, time_limit_min=attempt.time_limit_snapshot, now=utcnow()
            ),
            resumed=resumed,
            questions=[
                QuestionForAnswering(
                    question_id=d.question_id,
                    question_type=d.type_snapshot,
                    stem=d.stem_snapshot,
                    points=d.points_snapshot,
                    # ⚠️ 作答中**不帶 `is_correct`**——送出去等於把答案印在網頁原始碼裡
                    options=[
                        OptionForAnswering(option_id=o.option_id, text=o.text)
                        for o in parse_options_snapshot(d.options_snapshot)
                    ],
                    selected_options=parse_selected(d.selected_options),
                )
                for d in _in_snapshot_order(details, attempt.question_order)
            ],
        )


def _in_snapshot_order(details: list, question_order: str) -> list:
    """依 `QUESTION_ORDER` 快照排列明細。

    **不可依 `DETAIL_ID` 或 `QUESTION_ID` 排序**——那會讓同一次 attempt 在跳題前後看到
    不同的題序（AC 5 明訂同 attempt 內順序固定）。
    """
    import json

    order = {qid: i for i, qid in enumerate(json.loads(question_order))}
    return sorted(details, key=lambda d: order.get(d.question_id, len(order)))


def _to_result(detail, score: Decimal) -> QuestionResult:
    """組逐題明細——**此時才帶正確答案**（AC 11 強制顯示，無教師可關閉之選項）。"""
    options = parse_options_snapshot(detail.options_snapshot)
    selected = set(parse_selected(detail.selected_options))
    if score >= detail.points_snapshot and detail.points_snapshot > 0:
        outcome = OUTCOME_CORRECT
    elif score > 0 and detail.type_snapshot == QUESTION_MULTIPLE:
        outcome = OUTCOME_PARTIAL
    else:
        outcome = OUTCOME_WRONG
    return QuestionResult(
        question_id=detail.question_id,
        question_type=detail.type_snapshot,
        stem=detail.stem_snapshot,
        points=detail.points_snapshot,
        score=score,
        outcome=outcome,
        options=[
            OptionResult(option_id=o.option_id, text=o.text, is_correct=o.is_correct, selected=o.option_id in selected)
            for o in options
        ],
    )
