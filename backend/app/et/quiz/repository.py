"""ET 測驗 Repository（ET_QUIZ / ET_QUESTION / ET_OPTION；US3 / #203）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。更新型方法回傳受影響列數供 service 交給
`ensure_version_matched()` 判定樂觀鎖。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtChapter, EtItem
from app.et.progress.models import EtEnrollment
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM, EtQuizRetryReset

#: 測驗設定之預設值（data-model §ET_QUIZ）。
DEFAULT_PASS_SCORE = 80
DEFAULT_MAX_RETRY = 3


class EtQuizRepository:
    """`ET_QUIZ` 及其題目 / 選項之存取。"""

    async def create_shell(self, db: AsyncSession, name: str, operator: OperatorInfo) -> EtQuiz:
        """建立空殼測驗（無題目、採預設設定值）。

        與 `ET_ITEM` 於同一交易建立。「每測驗至少 1 題」**不在此檢核，也不在儲存時
        檢核**——教師是逐題新增的，空殼與第一題存檔之間必然存在 0 題的狀態。該條
        屬**發布時**檢核（FR-ET-US3-11，#204），見 `rules.py` 模組 docstring。
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
        """軟刪除題目與其選項。**學員的作答明細不動**。

        ## 為何不連帶軟刪除 `ET_QUIZ_ATTEMPT_D`（2026-09-04 / #279 SA 裁示 Q2 = C）

        2026-08-24 #202 曾加上連帶軟刪除，目的是「**不要硬刪掉學員資料**」（原 spec 規定
        hard delete，該次推翻）。但其代價清單只涵蓋 **#5 / #9 / #14** 三張**統計型**
        issue，**沒有列入 US6 的「學員回看自己那次考卷」**——是一個沒被想到的用途。

        照原本的連帶做下去，學員會看到「總分 75、明細只列 4 題加起來 60」這種自己對不
        起來的成績單：`ET_QUIZ_ATTEMPT_M.SCORE` 是閱卷當下算好凍結的，不因題目後來被刪
        而改變（也不該改，那是既成事實）。

        `ET_QUIZ_ATTEMPT_D` 是**自給自足**的——`STEM_SNAPSHOT` / `OPTIONS_SNAPSHOT` /
        `POINTS_SNAPSHOT` / `SELECTED_OPTIONS` 足以渲染明細，完全不需要讀 `ET_QUESTION`。
        題目被刪除對這筆明細沒有任何影響，除非我們自己去標記它。

        > 🔴 **給 `ET-9` / `ET-14` 的連帶約束**：成績統計一律讀
        > `ET_QUIZ_ATTEMPT_M.SCORE`（閱卷當下凍結的總分），**不得**回頭重新加總
        > `ET_QUIZ_ATTEMPT_D.SCORE`——重新加總等於不信任閱卷結果，而閱卷是依當時快照
        > 算的，事後任何改動都不該回頭影響它。

        `ET_QUIZ_ATTEMPT_M`（作答主檔）同樣不刪——刪的是題目、不是整場作答。整場作廢是
        刪除測驗時的事（見 `soft_delete_cascade`）。
        """
        if not question_ids:
            return
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": utcnow()}
        await db.execute(
            update(EtOption).where(EtOption.question_id.in_(question_ids), EtOption.deleted == 0).values(**audit)
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

    async def item_id_of_quiz(self, db: AsyncSession, quiz_id: int, *, course_id: int) -> int | None:
        """該測驗於**指定課程**內掛在哪個章節項目上（`ET_ITEM.ITEM_ID`）。

        測驗與課程的關聯**只經 `ET_ITEM.QUIZ_ID`**——`ET_QUIZ` 本身沒有 `COURSE_ID`。
        清除學員的完成旗標需要 `ITEM_ID`（`ET_PROGRESS` 以項目為單位），故另取一次。

        ⚠️ **以 `course_id` 收斂的理由**：`ET_ITEM.QUIZ_ID` 沒有唯一約束，而本查詢的
        `.limit(1)` 沒有 ORDER BY。同一測驗若掛在兩個項目上，這裡與
        `EtItemRepository.resolve_owner`（擁有者驗證的依據）可能挑到**不同課程**，
        於是清掉的是另一門課學員的完成旗標。呼叫端的 `course_id` 本來就由該測驗反推
        而來，帶進來即可讓兩處由建構上一致。

        比照 `tracking/repository.get_quiz_in_course` 的同一道防護。

        Returns:
            項目 ID；孤兒測驗或不屬於該課程者回 `None`。
        """
        return await db.scalar(
            select(EtItem.item_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtItem.quiz_id == quiz_id,
                EtItem.deleted == 0,
                EtChapter.course_id == course_id,
                EtChapter.deleted == 0,
            )
            .limit(1)
        )

    async def passed_student_attempt_counts(
        self, db: AsyncSession, quiz_id: int, *, course_id: int
    ) -> list[tuple[str, int]]:
        """該測驗於**指定課程**內**目前算通過**之學員，及其 attempt 總數。

        `attempt_count` 供 `add_retry_reset` 當新基準用——記重置當下的總數，之後
        `round_used_attempts(total, base)` 算出的本輪已用次數即從 0 起算。

        ## 🔴 是「目前算通過」，不是「曾及格」

        判定條件是「**在最近一次重置基準之後**仍有及格紀錄」，即
        `IS_PASS AND ATTEMPT_NO > MAX(ATTEMPT_COUNT_AT_RESET)`。

        ⚠️ 用「曾及格」（單純 `bool_or(IS_PASS)`）會讓這個值**重置後不會下降**，後果是：
        確認框永遠會跳（即使剛剛才重置過）、教師每按一次就再寄 N 封信、再寫 N 列
        `ET_QUIZ_RETRY_RESET`（append-only 只增不減）。「手滑連按三次 → 全班收三封」
        很容易發生。改用本定義後，重置完該學員自然不在名單內，重複儲存不會重寄。

        `ATTEMPT_NO > base` 之所以等於「在基準之後」：`attempt_no = total + 1`
        （`attempt/service.py`）且 attempt **永不刪除**，故序號連續無跳號、序號即位置。

        ⚠️ 及格與否用 `IS_PASS` 而非比對分數與當前 `PASS_SCORE`：及格在提交當下就以
        `PASS_SCORE_SNAPSHOT` 判定並寫入。拿當前及格分數回頭重算，會讓「教師調高及格
        分數」這個動作本身改變誰算通過過——而那正是本功能要處理的變更。

        ⛔ **排除已被移出課程者**（`ET_ENROLLMENT.IS_REMOVED`）。

        Returns:
            `[(user_id, attempt_count), ...]`，依 `user_id` 排序使結果可預期。
        """
        # 每位學員的重置基準（無紀錄者為 NULL → 下方 coalesce 為 0）。
        # 語意與 `tracking/repository.reset_base_of` 相同，只是一次取整批。
        bases = (
            select(
                EtQuizRetryReset.user_id.label("user_id"),
                func.max(EtQuizRetryReset.attempt_count_at_reset).label("base"),
            )
            .where(EtQuizRetryReset.quiz_id == quiz_id)
            .group_by(EtQuizRetryReset.user_id)
            .subquery()
        )
        base_col = func.coalesce(bases.c.base, 0)
        rows = await db.execute(
            select(EtQuizAttemptM.user_id, func.count())
            .join(
                EtEnrollment,
                (EtEnrollment.user_id == EtQuizAttemptM.user_id) & (EtEnrollment.course_id == EtQuizAttemptM.course_id),
            )
            .outerjoin(bases, bases.c.user_id == EtQuizAttemptM.user_id)
            .where(
                EtQuizAttemptM.quiz_id == quiz_id,
                EtQuizAttemptM.deleted == 0,
                # 以呼叫端已驗過擁有權的那門課收斂，理由同 `item_id_of_quiz`——
                # 不讓「同一測驗掛在多門課」的可能性擴散到受影響名單。
                EtQuizAttemptM.course_id == course_id,
                # ⛔ 已被移出課程者排除。`mark_removed` 只設 `IS_REMOVED`，不動
                # attempt 與 progress，所以不濾的話他會被寫重置基準、清完成旗標，
                # 還收到一封「請重新測驗」的信——而他已經不在這門課了。
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
            # `base_col` 每位學員恆為單一值，放進 GROUP BY 不改變分組，只是讓它能
            # 出現在 HAVING 裡（Postgres 不允許 HAVING 直接引用未分組的欄位）。
            .group_by(EtQuizAttemptM.user_id, base_col)
            .having(func.bool_or(EtQuizAttemptM.is_pass & (EtQuizAttemptM.attempt_no > base_col)))
            .order_by(EtQuizAttemptM.user_id)
        )
        return [(uid, cnt) for uid, cnt in rows.all()]
