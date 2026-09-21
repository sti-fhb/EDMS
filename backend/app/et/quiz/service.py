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
from app.core.utils import utcnow
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtCourseRepository, EtItemRepository
from app.et.course.rules import ensure_owner, is_browsable_by_non_owner
from app.et.notify.course_invite import learn_link
from app.et.notify.quiz_retest_required import QuizRetestRequiredMailer
from app.et.progress.repository import EtProgressRepository
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
from app.et.tracking.repository import EtTrackingRepository
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此測驗", error_code="ET_QUIZ_001")
_QUESTION_NOT_FOUND = AppError(status_code=404, detail="查無此題目", error_code="ET_QUESTION_001")


def _ensure_browsable(*, owner_id: str, actor_id: str, status: str, open_end_at) -> None:
    """非擁有者只能讀「已發布且期間未過」的課程（#358 M-1 / `spec_us3` AC 8）。

    🔴 **這支只能用在讀取路徑。** 寫入路徑走 `ensure_owner`（403）——把本判定放進兩者
    共用的 `_resolve_quiz` 會讓非擁有者對他人**草稿**的寫入從 403 變成 404，而那三條
    寫入防護測試正是這樣抓到的。

    唯讀瀏覽的入口是 ET01「全部課程」清單，它只列符合此條件者；不判的話「清單上看
    不到、但用 id 直接打 API 讀得到他人草稿的題庫」，違反 `spec_us3` AC 8。

    回 404 而非 403：與孤兒測驗同一個處理，不揭露「這筆存在但你看不到」。
    """
    if owner_id == actor_id:
        return
    if not is_browsable_by_non_owner(status=status, open_end_at=open_end_at, now=utcnow()):
        raise _NOT_FOUND


class EtQuizService:
    """測驗設定、題目與選項之編修。"""

    def __init__(
        self,
        quizzes: EtQuizRepository | None = None,
        items: EtItemRepository | None = None,
        audit: AuditLogService | None = None,
        tracking: EtTrackingRepository | None = None,
        progress: EtProgressRepository | None = None,
        courses: EtCourseRepository | None = None,
        mailer: QuizRetestRequiredMailer | None = None,
    ) -> None:
        self._quizzes = quizzes or EtQuizRepository()
        self._items = items or EtItemRepository()
        self._audit = audit or AuditLogService()
        # #361：要求已通過學員重測時要寫重置基準與清完成旗標，兩者的表分屬 tracking
        # 與 progress。⚠️ 只用它們的 **repository**，不繞道各自的 service——後者帶有
        # 自己的守門（如 `can_reset_retry` 拒絕已通過者），與本路徑的前提相反。
        self._tracking = tracking or EtTrackingRepository()
        self._progress = progress or EtProgressRepository()
        self._courses = courses or EtCourseRepository()
        self._mailer = mailer or QuizRetestRequiredMailer()

    async def get_detail(self, db: AsyncSession, quiz_id: int, *, actor_id: str) -> QuizDetail:
        """測驗詳細——設定、題目與選項一次帶齊，並附配分總和。

        ## 他人課程可讀，但**看不到答案**（#358 第 2 項，SA 裁示 2026-09-17）

        `FR-ET-US7-04` 明訂他人建立之課程可唯讀瀏覽，原本此處走 `_require_owned` 而回
        403，於是教師乙開啟教師甲的課程、點開測驗視窗只看到空白。

        但整份開放會開一個洞：本回應含 `OptionRow.is_correct`（完整答案），而
        `spec.md` §多重角色明訂**同一人可兼具教師與學員**，且 `quiz_id` 在學員端的
        學習頁拿得到——等於讓兼具兩種角色的人先看自己正要考的答案。

        故非擁有者取得的是「題目可讀、答案遮蔽」：`is_correct` 一律為 `None`，並以
        `answers_visible=False` 明示（不是遮成 `False`——那會顯示「0 個正解」，是錯誤
        資訊而非隱藏）。
        """
        quiz, resolved = await self._resolve_quiz(db, quiz_id)
        _ensure_browsable(
            owner_id=resolved.owner_id, actor_id=actor_id, status=resolved.status, open_end_at=resolved.open_end_at
        )
        answers_visible = resolved.owner_id == actor_id
        questions = await self._quizzes.list_questions(db, quiz_id)
        options = await self._quizzes.list_options(db, [q.question_id for q in questions])

        by_question: dict[int, list[OptionRow]] = {}
        for option in options:
            row = OptionRow.model_validate(option)
            if not answers_visible:
                row = row.model_copy(update={"is_correct": None})
            by_question.setdefault(option.question_id, []).append(row)

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
            answers_visible=answers_visible,
            # 只有擁有者拿得到人數：非擁有者給 `None`（不是 0），理由同 `is_correct` 的遮蔽。
            passed_count=(
                len(await self._quizzes.passed_student_attempt_counts(db, quiz_id)) if answers_visible else None
            ),
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
        affected = await self._require_retest_if_asked(
            db, quiz_id=quiz_id, course_id=course_id, asked=req.require_retest, operator=operator
        )
        await self._log(db, "UPDATE", operator.user_id, course_id, self._with_retest("更新測驗設定", affected))

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
        affected = await self._require_retest_if_asked(
            db, quiz_id=quiz_id, course_id=course_id, asked=req.require_retest, operator=operator
        )
        await self._log(db, "CREATE", operator.user_id, course_id, self._with_retest("新增測驗題目", affected))
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
        affected = await self._require_retest_if_asked(
            db, quiz_id=question.quiz_id, course_id=course_id, asked=req.require_retest, operator=operator
        )
        await self._log(db, "UPDATE", operator.user_id, course_id, self._with_retest("更新測驗題目", affected))

    async def delete_question(
        self, db: AsyncSession, question_id: int, *, require_retest: bool = False, operator: OperatorInfo
    ) -> None:
        """刪除題目：本體與選項軟刪，剩餘題目順序遞補。

        🔴 **學員作答明細（`ET_QUIZ_ATTEMPT_D`）不動**（#279 裁示 Q2 = C，2026-09-04
        推翻 #202 的連帶軟刪）。`soft_delete_questions` 只 update `ET_OPTION` 與
        `ET_QUESTION`，`test_et_quiz.py::test_刪除題目軟刪選項但不動學員作答明細` 釘住
        此行為。

        ⛔ **不要為了「已刪題目不該計分」而把連帶加回來**。`ET_QUIZ_ATTEMPT_D` 是
        自給自足的快照（題幹／選項／配分都存在裡面），而成績統計一律讀
        `ET_QUIZ_ATTEMPT_M.SCORE`、**不回頭重新加總**。加回連帶的症狀是學員看到
        「總分 75、明細只列 4 題加起來 60」這種自己對不起來的成績單。

        Args:
            require_retest: 是否要求已通過的學員重新測驗（#361）。刪題是題目內容變更，
                故提供此選項；實際行為見 `_require_retest_if_asked`。
        """
        question = await self._quizzes.get_question(db, question_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        _, course_id = await self._require_owned(db, question.quiz_id, operator.user_id)
        await self._quizzes.soft_delete_questions(db, [question_id], operator)
        await self._quizzes.resequence_questions(db, question.quiz_id, operator)
        affected = await self._require_retest_if_asked(
            db, quiz_id=question.quiz_id, course_id=course_id, asked=require_retest, operator=operator
        )
        await self._log(db, "DELETE", operator.user_id, course_id, self._with_retest("刪除測驗題目", affected))

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

    async def _resolve_quiz(self, db: AsyncSession, quiz_id: int):
        """取測驗與其所屬課程，**不判擁有者**——供唯讀路徑使用。

        Returns:
            `(quiz, ResolvedCourse)`——後者含 `course_id` / `owner_id` / `status` /
            `open_end_at`，供呼叫端自行決定要套哪一道守門。

        ⚠️ 這支**不是**守門。讀取路徑要接 `_ensure_browsable`，寫入路徑要接
        `ensure_owner`（見 `_require_owned`）。把任何一道守門塞進本函式都會污染另一條
        路徑——#358 M-1 的第一版就是這樣讓非擁有者對他人草稿的寫入從 403 變成 404。
        """
        quiz = await self._quizzes.get(db, quiz_id)
        if quiz is None:
            raise _NOT_FOUND
        resolved = await self._items.resolve_owner(db, quiz_id=quiz_id)
        if resolved is None:
            raise _NOT_FOUND  # 孤兒測驗：UI 無從到達，不揭露其存在
        return quiz, resolved

    async def _require_owned(self, db: AsyncSession, quiz_id: int, actor_id: str):
        """取測驗並確認擁有者——**寫入路徑專用**。

        讀取請用 `_resolve_quiz`（#358 第 2 項：他人課程可唯讀瀏覽，但答案遮蔽）。
        """
        quiz, resolved = await self._resolve_quiz(db, quiz_id)
        ensure_owner(owner_id=resolved.owner_id, actor_id=actor_id)
        return quiz, resolved.course_id

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

    async def _require_retest_if_asked(
        self, db: AsyncSession, *, quiz_id: int, course_id: int, asked: bool, operator: OperatorInfo
    ) -> int:
        """教師選「要求重測」時，把該測驗的已通過學員退回未通過（#361）。

        對每位已通過的學員做兩件事，**同一交易**：

        1. 寫一列 `ET_QUIZ_RETRY_RESET` 基準 → 本輪已用次數歸 0
        2. 清除該測驗項目的 `ET_PROGRESS.IS_COMPLETED` → 完課狀態隨之回退

        ⛔ **不刪任何 attempt**。學員與教師仍可回看歷次明細（US6 AC 12 / US9 AC 6），
        且 `ET_QUIZ_ATTEMPT_D` 是自給自足的快照，舊紀錄不因題目改動而錯亂。

        ## 🔴 為何不重用 `tracking.reset_retry`

        兩者**前提相反**。`can_reset_retry` 在 `is_passed=True` 時回 `False`，理由是
        「他已經通過了；再考只有機會把成績弄低」——那條守門保護的是**教師手動**重置
        一位卡住的學員（US9 AC 6）。本功能的對象**正是已通過的人**，是測驗內容變了
        才要他重考，不是他考壞了要救他。

        ⛔ **不要為了重用而放寬 `can_reset_retry`**，也不要把兩條路徑「統一」——那會讓
        教師又能對已通過的學員按重置，把成績弄低。兩條看似重複的路徑是刻意的。

        ## 🔴 為何稽核不在迴圈裡

        `log_action` 的第一步是 `pg_advisory_xact_lock`——**單一固定 key 的交易層級鎖，
        持有到外層交易 commit**。在迴圈內呼叫的話，第一位學員就取走它，之後整批的
        UPDATE 與寄信全在持鎖狀態下進行，而那把鎖是全平台共用的（**包含登入**）。

        形狀比照 `app/et/approval/service.py::approve`：迴圈只寫業務資料，稽核累積後
        統一寫。⚠️ 本函式回傳受影響人數，由呼叫端在既有的 `_log` 裡一次記錄。

        Returns:
            受影響的學員人數；`asked=False` 或無人通過時為 0。
        """
        if not asked:
            return 0
        item_id = await self._quizzes.item_id_of_quiz(db, quiz_id)
        if item_id is None:
            return 0  # 孤兒測驗：沒有項目就沒有進度可清，也不會有學員作答
        affected = await self._quizzes.passed_student_attempt_counts(db, quiz_id)
        if not affected:
            return 0

        quiz = await self._quizzes.get(db, quiz_id)
        course = await self._courses.get(db, course_id)
        course_url = learn_link(course_id)

        # 兩項寫入**批次化**：本批次的人數由系統決定、沒有上限（不像教師勾選的核可
        # 批次有 100 筆 schema 上限），逐筆寫等於 2N 次往返。
        await self._tracking.add_retry_resets(
            db, course_id=course_id, quiz_id=quiz_id, entries=affected, operator=operator
        )
        await self._progress.set_item_completed_bulk(
            db,
            user_ids=[user_id for user_id, _ in affected],
            course_id=course_id,
            item_id=item_id,
            completed=False,
            operator=operator,
        )

        # ⚠️ 寄信**不能**比照批次化：範本內文含 `{USER_NAME}`，而平台 `send_email`
        # 對整批收件人只渲染一次——合批會讓所有人收到同一個名字的信。這是範本渲染
        # 的硬限制，不是還沒優化。
        #
        # 寄信在迴圈內、稽核在迴圈外，兩者刻意不同：寄信不取全域鎖，`log_action` 會。
        for user_id, _ in affected:
            await self._mailer.send_quiz_retest_required(
                db, course=course, quiz_name=quiz.quiz_name, course_url=course_url, user_id=user_id
            )
        return len(affected)

    @staticmethod
    def _with_retest(description: str, affected: int) -> str:
        """把「本次一併要求 N 位已通過學員重測」併進稽核描述。

        ⚠️ 不併的話，`DP_AUDIT_LOG` 只會看到「更新測驗設定」，看不出這一下讓 N 位
        學員的通過紀錄被清掉——而那是本動作最重的後果。資訊雖然也在
        `ET_QUIZ_RETRY_RESET`，但追溯時不會有人先想到去查那張表。
        """
        return description if affected == 0 else f"{description}，並要求 {affected} 位已通過學員重測"

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
