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
from app.et.constants import COURSE_PUBLISHED
from app.et.course.repository import EtCourseRepository, EtItemRepository
from app.et.course.rules import ensure_owner, is_browsable_by_non_owner, is_effectively_closed
from app.et.course.stage_rules import ENTITY_OPTION, ENTITY_QUESTION, ENTITY_QUIZ, RETEST_PAYLOAD_KEY
from app.et.course.stage_writer import EtCourseStageWriter, exposed_id, is_staged
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
_LAST_QUESTION = AppError(
    status_code=409,
    detail="測驗至少須有 1 題，已發布課程不可刪除最後一題",
    error_code="ET_QUESTION_005",
)


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
        stage_writer: EtCourseStageWriter | None = None,
    ) -> None:
        self._stage_writer = stage_writer or EtCourseStageWriter()
        self._quizzes = quizzes or EtQuizRepository()
        self._items = items or EtItemRepository()
        self._audit = audit or AuditLogService()
        # #361：要求學員重測時要寫重置基準與清完成旗標，兩者的表分屬 tracking
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
        # 擁有者 + 已開始編輯 ⇒ 讀暫存版（#631）。少了這段，教師開啟測驗看到的是學員
        # 那一版，存檔時整份取代，他上一次的暫存編輯被自己的畫面蓋回去。
        staged = await self._staged_detail(db, quiz_id, actor_id)
        if staged is not None:
            return staged

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
            affected_count=(
                len(await self._quizzes.retest_target_attempt_counts(db, quiz_id, course_id=resolved.course_id))
                if answers_visible
                else None
            ),
        )

    async def update_settings(
        self, db: AsyncSession, quiz_id: int, req: QuizUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新測驗設定（名稱、說明、及格分數、時間限制、重考上限）。

        `description` 為**純文字**（SA 裁示 #203 Q1），與教材說明文字分屬兩條路徑——
        **不經 HTML 消毒**，前端亦須以純文字渲染。
        """
        ref, course_id = await self._staged_quiz(db, quiz_id, operator.user_id, operator)
        if ref is not None:
            # ⚠️ 整份取代，所有欄位都要送（見 `update_payload` 的 docstring）
            rowcount = await self._stage_writer.update_payload(
                db,
                ref.stage_id,
                version=req.version,
                payload={
                    "quiz_name": req.quiz_name,
                    "description": req.description,
                    "pass_score": req.pass_score,
                    "time_limit_min": req.time_limit_min,
                    "max_retry": req.max_retry,
                },
                operator=operator,
            )
            ensure_version_matched(rowcount=rowcount, entity="ET_QUIZ")
            # 🔴 **測驗設定這一支是旗標的開關，勾與不勾都要生效**
            # （2026-10-18 security review M-1 後半）。
            #
            # 原本只在 `require_retest` 為真時設旗標，為假時什麼都不做 ⇒ 教師誤勾之後
            # **沒有任何方式取消**：再存一次不勾也清不掉，只能 `discard` 整個工作階段、
            # 連同其他編輯一起丟。而這個旗標的後果是「全班已通過的人被退回並收到信」，
            # 不可逆。
            #
            # ⚠️ 只有本支這樣做。`add_question` / `update_question` / `delete_question`
            # 的 `require_retest=false` **不清除**旗標——那是「這一次改題不另外要求重測」，
            # 不是「取消先前的要求」。測驗設定頁才是那個勾選框的所在地。
            await self._stage_require_retest(
                db, quiz_stage_id=ref.stage_id, operator=operator, wanted=req.require_retest
            )
            # 稽核不記受影響人數——此刻還沒有人被影響（重測延到「更新」當下才執行）
            await self._log(db, "UPDATE", operator.user_id, course_id, "更新測驗設定（暫存）")
            return

        _, resolved = await self._require_owned(db, quiz_id, operator.user_id)
        course_id = resolved.course_id
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
        ref, course_id = await self._staged_quiz(db, quiz_id, operator.user_id, operator)
        self._validate_options(req)
        if ref is not None:
            question_stage = await self._stage_writer.append(
                db,
                ref.course_id,
                ENTITY_QUESTION,
                parent_stage_id=ref.stage_id,
                payload={"question_type": req.question_type, "stem": req.stem, "points": req.points},
                operator=operator,
            )
            for option in req.options:
                await self._stage_writer.append(
                    db,
                    ref.course_id,
                    ENTITY_OPTION,
                    parent_stage_id=question_stage,
                    payload={"option_text": option.option_text, "is_correct": option.is_correct},
                    operator=operator,
                )
            if req.require_retest:
                await self._stage_require_retest(db, quiz_stage_id=ref.stage_id, operator=operator)
            await self._log(db, "CREATE", operator.user_id, course_id, "新增測驗題目（暫存）")
            return await self._staged_question_row(db, ref.course_id, question_stage)

        _, resolved = await self._require_owned(db, quiz_id, operator.user_id)
        course_id = resolved.course_id
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
        ref, course_id, live_quiz_id = await self._staged_question(db, question_id, operator.user_id, operator)
        self._validate_options(req)
        if ref is not None:
            rowcount = await self._stage_writer.update_payload(
                db,
                ref.stage_id,
                version=req.version,
                payload={"question_type": req.question_type, "stem": req.stem, "points": req.points},
                operator=operator,
            )
            ensure_version_matched(rowcount=rowcount, entity="ET_QUESTION")
            # 選項**全量覆寫**：舊的整批移除再依送來的順序新增，與活表路徑的
            # `replace_question` 同語意。⛔ 不要改成「比對差異」——選項沒有穩定的業務鍵
            # （同一題可以有兩個同名選項），比對必然在某些情況下配錯。
            for old in await self._stage_writer.children_of(db, ref.course_id, ENTITY_OPTION, ref.stage_id):
                await self._stage_writer.delete_subtree(db, old.stage_id, operator)
            for option in req.options:
                await self._stage_writer.append(
                    db,
                    ref.course_id,
                    ENTITY_OPTION,
                    parent_stage_id=ref.stage_id,
                    payload={"option_text": option.option_text, "is_correct": option.is_correct},
                    operator=operator,
                )
            if req.require_retest:
                node = await self._stage_writer.node_by_stage_id(db, ref.stage_id, ENTITY_QUESTION)
                if node is not None and node.parent_stage_id is not None:
                    await self._stage_require_retest(db, quiz_stage_id=node.parent_stage_id, operator=operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "更新測驗題目（暫存）")
            return

        question = await self._quizzes.get_question(db, question_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        _ = live_quiz_id
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
            require_retest: 是否要求學員重新測驗（#361 / #709）。刪題是題目內容變更，
                故提供此選項；實際行為見 `_require_retest_if_asked`。
        """
        ref, course_id, _live_quiz_id = await self._staged_question(db, question_id, operator.user_id, operator)
        if ref is not None:
            # 🔴 **暫存模式不套 #410 的「不可刪最後一題」**（2026-10-17 使用者裁示）。
            #
            # 那道守門補的是一個**時間差**：`BLOCK_QUIZ_NO_QUESTION` 原本只在發布 / 再開課
            # 跑，發布後把題刪光沒人再檢核。而「更新」現在也會跑同一套檢核——時間差沒了，
            # 刪除也碰不到學員（只進暫存區）。再擋的話，擋住的是「先刪光再重建題庫」這個
            # 合法的編輯順序，而規則本身仍由「更新」守著。
            #
            # ⚠️ 草稿與活表路徑的守門**照舊**（見 `_ensure_not_last_question_of_live_course`）。
            node = await self._stage_writer.node_by_stage_id(db, ref.stage_id, ENTITY_QUESTION)
            quiz_stage_id = None if node is None else node.parent_stage_id
            await self._stage_writer.delete_subtree(db, ref.stage_id, operator)
            if require_retest and quiz_stage_id is not None:
                await self._stage_require_retest(db, quiz_stage_id=quiz_stage_id, operator=operator)
            await self._log(db, "DELETE", operator.user_id, course_id, "刪除測驗題目（暫存）")
            return

        question = await self._quizzes.get_question(db, question_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        _, resolved = await self._require_owned(db, question.quiz_id, operator.user_id)
        course_id = resolved.course_id
        await self._ensure_not_last_question_of_live_course(db, quiz_id=question.quiz_id, resolved=resolved)
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
        ref, course_id = await self._staged_quiz(db, quiz_id, operator.user_id, operator)
        if ref is not None:
            nodes = await self._stage_writer.children_of(db, ref.course_id, ENTITY_QUESTION, ref.stage_id)
            by_exposed = {exposed_id(source_id=n.source_id, stage_id=n.stage_id): n.stage_id for n in nodes}
            ensure_question_reorder_complete(current_ids=set(by_exposed), requested=req.question_ids)
            # 併發令牌仍是**測驗層**的 `VERSION`（暫存列自己的），與活表路徑同形狀
            rowcount = await self._stage_writer.bump_version(db, ref.stage_id, req.version, operator)
            ensure_version_matched(rowcount=rowcount, entity="ET_QUIZ")
            await self._stage_writer.apply_order(db, [by_exposed[i] for i in req.question_ids], operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "調整測驗題目順序（暫存）")
            return

        _, resolved = await self._require_owned(db, quiz_id, operator.user_id)
        course_id = resolved.course_id
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

    async def _ensure_not_last_question_of_live_course(self, db: AsyncSession, *, quiz_id: int, resolved) -> None:
        """已發布且學員仍可作答的課程，其測驗不得被刪到 0 題（#410）。

        ## 🔴 2026-10-17 起**這道守門已不可達**，留著是為了讓下一個人看得懂歷史

        它只在活表路徑跑，而 #631 之後活表路徑只剩草稿課程（`is_staged` 的判準是
        「非草稿」）；本函式第一個條件又是 `status == COURSE_PUBLISHED`——草稿永遠不符。
        兩者相乘 ⇒ 恆不觸發。

        ⚠️ **不可達不等於可以刪掉後就沒事**：它承接的規則沒有消失，只是改由「更新」
        那一關（`BLOCK_QUIZ_NO_QUESTION`）守著，見
        `test_已發布課程刪最後一題進暫存且更新時被擋`。刪掉本函式之前，請先確認那一關
        還在——否則就是把一條規則從「兩道守門」降成「零道」。

        ⚠️ 若日後有任何路徑讓已發布課程的刪除繞過暫存區（例如為了某個批次工具），
        本函式會重新變成唯一的防線，那時它就不是死碼了。

        ## 以下為原始說明（#410 當初要補的時間差）

        ## 這道守門補的是一個**時間差**，不是一條新規則

        規則早就有——`course/publish_rules.BLOCK_QUIZ_NO_QUESTION`（「測驗至少須有 1 題」）。
        但 `evaluate_publish` 全專案只有一個呼叫點（`publish_service._blockers`，`publish` 與
        `reopen` 共用），所以它**只在發布／再開課那一刻跑**；發布之後教師把題目全刪掉，
        沒有任何地方會再檢核。本函式把同一條規則補到編輯路徑上。

        ## 後果為何值得擋

        `attempt/service.start` 對 0 題測驗回 404（建一個零題 attempt 會白吃一次作答次數），
        該項目因此永遠拿不到 `IS_COMPLETED`。而完課要求**每一項**皆完成
        （`enrollment/rules.is_course_completed`），於是**整門課永遠無法完課**，連帶
        課後問卷入口（US13 AC 1）與線下核可（US16）都拿不到——而教師端完全沒有訊號。

        ## ⛔ 這道守門**不取代** `progress/rules.build_item_state` 的 0 題例外

        兩層方向相反、互補：

        | 層 | 作用 | 保護對象 |
        |---|---|---|
        | 本函式（上游）| 讓新資料進不了 0 題狀態 | 未來 |
        | `build_item_state`（下游，#361）| 既有的 0 題測驗不鎖死學員 | 本守門上線**前**已存在的資料 |

        只做上游，守門上線前已是 0 題的測驗仍會鎖死學員；只做下游，此狀態會持續被製造。

        ## 為何範圍是「已發布**且**未視同關閉」

        - **草稿不納入**：教師逐題建立時必然經過 0 題，擋住會讓「建了一題想換掉」做不到
        - **視同關閉不納入**：`is_effectively_closed` 的課程學員本來就不能作答，0 題測驗
          傷不到任何人（`is_browsable_by_non_owner` 那條路已擋在學員端）

        Raises:
            AppError: 已發布課程之測驗僅剩 1 題（409 `ET_QUESTION_005`）。
        """
        if resolved.status != COURSE_PUBLISHED:
            return
        if is_effectively_closed(status=resolved.status, open_end_at=resolved.open_end_at, now=utcnow()):
            return
        remaining = await self._quizzes.list_questions(db, quiz_id)
        if len(remaining) <= 1:
            raise _LAST_QUESTION

    async def _require_owned(self, db: AsyncSession, quiz_id: int, actor_id: str):
        """取測驗並確認擁有者——**寫入路徑專用**。

        讀取請用 `_resolve_quiz`（#358 第 2 項：他人課程可唯讀瀏覽，但答案遮蔽）。
        """
        quiz, resolved = await self._resolve_quiz(db, quiz_id)
        ensure_owner(owner_id=resolved.owner_id, actor_id=actor_id)
        return quiz, resolved

    async def _staged_question_row(self, db: AsyncSession, course_id: int, question_stage_id: int) -> QuestionRow:
        """暫存版的 `_question_row`——id 一律走 `exposed_id`（新增的回負數）。"""
        node = await self._stage_writer.node_by_stage_id(db, question_stage_id, ENTITY_QUESTION)
        if node is None:  # pragma: no cover - 剛寫進去的節點必定讀得回來
            raise _QUESTION_NOT_FOUND
        options = await self._stage_writer.children_of(db, course_id, ENTITY_OPTION, question_stage_id)
        return QuestionRow(
            question_id=exposed_id(source_id=node.source_id, stage_id=node.stage_id),
            question_type=str(node.payload.get("question_type") or ""),
            stem=str(node.payload.get("stem") or ""),
            points=int(node.payload.get("points") or 0),
            sort_order=node.sort_order,
            version=node.version,
            options=[
                OptionRow(
                    option_id=exposed_id(source_id=o.source_id, stage_id=o.stage_id),
                    option_text=str(o.payload.get("option_text") or ""),
                    is_correct=bool(o.payload.get("is_correct")),
                    sort_order=o.sort_order,
                )
                for o in options
            ],
        )

    async def _staged_detail(self, db: AsyncSession, quiz_id: int, actor_id: str) -> QuizDetail | None:
        """暫存版的測驗詳細；回 `None` 代表沒有暫存區、該走活表。

        ⚠️ **只對擁有者**：他人讀到的必須是學員看得到的那一版（同 `get_detail` 的理由）。
        因此這裡的 `answers_visible` 恆為 `True`——非擁有者根本進不來這條路徑。
        """
        node = await self._stage_writer.node_of(db, quiz_id, ENTITY_QUIZ)
        if node is None:
            return None
        course = await self._courses.get(db, node.course_id)
        if course is None or course.owner_id != actor_id:
            return None
        questions = await self._stage_writer.children_of(db, node.course_id, ENTITY_QUESTION, node.stage_id)
        rows = [await self._staged_question_row(db, node.course_id, q.stage_id) for q in questions]
        return QuizDetail(
            quiz_id=quiz_id,
            quiz_name=str(node.payload.get("quiz_name") or ""),
            description=node.payload.get("description"),
            pass_score=int(node.payload.get("pass_score") or 0),
            time_limit_min=node.payload.get("time_limit_min"),
            max_retry=int(node.payload.get("max_retry") or 0),
            version=node.version,
            questions=rows,
            points_total=sum(r.points for r in rows),
            answers_visible=True,
            # ⚠️ 受影響人數取的是**活表**的作答紀錄——那是事實，與編輯中的題目無關。
            # 新增的測驗（`source_id` 為 None）還沒有人考過，回 0。
            affected_count=(
                0
                if node.source_id is None
                else len(await self._quizzes.retest_target_attempt_counts(db, node.source_id, course_id=node.course_id))
            ),
            # 🔴 回讀勾選狀態，否則前端只能預設未勾，而存檔會把它清掉。見 schema 的說明。
            require_retest_pending=bool(node.payload.get(RETEST_PAYLOAD_KEY)),
        )

    async def _staged_quiz(self, db: AsyncSession, quiz_id: int, actor_id: str, operator):
        """測驗 id → 暫存節點；回 `(None, course_id)` 代表該走活表路徑（#631 PR 2b）。

        形狀同 `course/service._staged_chapter`：負數先解析 → 授權 → **取鎖** → 取節點。
        """
        ref = await self._stage_writer.resolve_new(db, quiz_id, ENTITY_QUIZ)
        if ref is not None:
            course = await self._courses.get(db, ref.course_id)
            if course is None:
                raise _NOT_FOUND
            ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            return ref, ref.course_id

        _, resolved = await self._require_owned(db, quiz_id, actor_id)
        course = await self._courses.get(db, resolved.course_id)
        if not is_staged(course):
            return None, resolved.course_id
        await self._stage_writer.lock_course(db, resolved.course_id)
        ref = await self._stage_writer.ref_for_source(
            db, resolved.course_id, ENTITY_QUIZ, quiz_id, operator, gone_error=_NOT_FOUND
        )
        return ref, resolved.course_id

    async def _staged_question(self, db: AsyncSession, question_id: int, actor_id: str, operator):
        """題目 id → 暫存節點；回 `(None, course_id, quiz_id)` 代表該走活表路徑。

        回傳也帶 `quiz_id`（活表路徑用）／`parent_stage_id`（暫存路徑用）——`require_retest`
        的對象是**測驗**不是題目，兩條路徑都要知道是哪一個測驗。
        """
        ref = await self._stage_writer.resolve_new(db, question_id, ENTITY_QUESTION)
        if ref is None:
            question = await self._quizzes.get_question(db, question_id)
            if question is None:
                raise _QUESTION_NOT_FOUND
            _, resolved = await self._require_owned(db, question.quiz_id, actor_id)
            course = await self._courses.get(db, resolved.course_id)
            if not is_staged(course):
                return None, resolved.course_id, question.quiz_id
            await self._stage_writer.lock_course(db, resolved.course_id)
            ref = await self._stage_writer.ref_for_source(
                db, resolved.course_id, ENTITY_QUESTION, question_id, operator, gone_error=_QUESTION_NOT_FOUND
            )
            return ref, resolved.course_id, question.quiz_id

        course = await self._courses.get(db, ref.course_id)
        if course is None:
            raise _QUESTION_NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        await self._stage_writer.lock_course(db, ref.course_id)
        return ref, ref.course_id, None

    async def _stage_require_retest(
        self, db: AsyncSession, *, quiz_stage_id: int, operator: OperatorInfo, wanted: bool = True
    ) -> None:
        """把「要求重測」的意圖**記在測驗的暫存節點上，等按『更新』才執行**（#631）。

        ## 為何不在編輯當下執行（2026-10-17 使用者裁示）

        暫存模式下，學員被退回未通過的那一刻**新題目還沒生效**。他去重考，考的是他剛剛
        才通過的同一份舊題——副作用先發生、原因還看不到。與 #303 的通知改到「更新」當下
        寄是同一個道理：副作用要跟著「學員看得到了」一起發生。

        ## 為何寄在 payload 而不是另開欄位

        這個意圖的生命週期**與暫存工作階段完全一致**：放棄編輯就該一起消失，套用完就該
        清掉。暫存列本來就是這兩件事的載體，另開欄位反而要自己維護那兩個時點。

        ⚠️ `_RETEST_KEY` **不是 `ET_QUIZ` 的欄位**，所以 `stage_apply._upsert` 會自動忽略
        它（它只寫 `payload_fields(spec)` 列出的 key）。⛔ 不要把它改成與欄位同名。

        ⚠️ 一次工作階段內勾選多次只記一次：重測是「做或不做」，不累加。

        ⚠️ 走 `set_payload_flag` 而非 `update_payload`：後者會遞增 `VERSION`，而那是教師
        那一端的樂觀鎖令牌。為一個他沒改的東西推進版本，會讓他**下一次存檔無故 409**。

        Args:
            wanted: `False` 時**清除**旗標。只有測驗設定那一支會傳 `False`——它是那個
                勾選框的所在地，所以不勾就該取消。改題 / 刪題的 `require_retest=false`
                意思是「這一次不另外要求」，不是「取消先前的要求」，故維持預設 `True`。
        """
        await self._stage_writer.set_payload_flag(
            db, quiz_stage_id, RETEST_PAYLOAD_KEY, True if wanted else None, operator
        )

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

    async def require_retest_now(
        self, db: AsyncSession, *, quiz_id: int, course_id: int, operator: OperatorInfo
    ) -> int:
        """立刻執行「要求重測」——供 `stage_apply` 於套用當下呼叫（#631）。

        暫存模式下教師勾選時只記意圖（見 `_stage_require_retest`），真正執行延到按
        「更新」。本方法是那個執行點對外的入口。

        ⛔ 不要把 `_require_retest_if_asked` 直接公開：它帶著 `asked` 參數，而呼叫端
        在套用時已經過濾過旗標，再傳一次布林只會多一個可以傳錯的地方。
        """
        return await self._require_retest_if_asked(
            db, quiz_id=quiz_id, course_id=course_id, asked=True, operator=operator
        )

    async def _require_retest_if_asked(
        self, db: AsyncSession, *, quiz_id: int, course_id: int, asked: bool, operator: OperatorInfo
    ) -> int:
        """教師選「要求重測」時，讓該測驗作答過的學員從新一輪開始（#361；#709 起不限已通過者）。

        對象見 `retest_target_attempt_counts`。對每位學員做兩件事，**同一交易**：

        1. 寫一列 `ET_QUIZ_RETRY_RESET` 基準 → 本輪已用次數歸 0
        2. 清除該測驗項目的 `ET_PROGRESS.IS_COMPLETED` → 完課狀態隨之回退

        ⛔ **不刪任何 attempt**。學員與教師仍可回看歷次明細（US6 AC 12 / US9 AC 6），
        且 `ET_QUIZ_ATTEMPT_D` 是自給自足的快照，舊紀錄不因題目改動而錯亂。

        ## 🔴 為何不重用 `tracking.reset_retry`

        兩者**前提相反**。`can_reset_retry` 在 `is_passed=True` 時回 `False`，理由是
        「他已經通過了；再考只有機會把成績弄低」——那條守門保護的是**教師手動**重置
        一位卡住的學員（US9 AC 6）。本功能的對象**包含已通過的人**，是測驗內容變了
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
            受影響的學員人數；`asked=False` 或無人作答時為 0。
        """
        if not asked:
            return 0
        item_id = await self._quizzes.item_id_of_quiz(db, quiz_id, course_id=course_id)
        if item_id is None:
            return 0  # 孤兒測驗：沒有項目就沒有進度可清，也不會有學員作答
        affected = await self._quizzes.retest_target_attempt_counts(db, quiz_id, course_id=course_id)
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
        """把「本次一併要求 N 位學員重測」併進稽核描述。

        ⚠️ 不併的話，`DP_AUDIT_LOG` 只會看到「更新測驗設定」，看不出這一下讓 N 位
        學員的通過紀錄被清掉——而那是本動作最重的後果。資訊雖然也在
        `ET_QUIZ_RETRY_RESET`，但追溯時不會有人先想到去查那張表。
        """
        return description if affected == 0 else f"{description}，並要求 {affected} 位學員重測"

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
