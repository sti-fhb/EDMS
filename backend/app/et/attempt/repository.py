"""ET06 測驗作答之查詢與寫入（US6 / #279）。

## 兩張表的分工

| 表 | 粒度 | 內容 |
|---|---|---|
| `ET_QUIZ_ATTEMPT_M` | 一次作答 | 順序快照、及格分數 / 時限快照、總分、狀態 |
| `ET_QUIZ_ATTEMPT_D` | 一題一列 | 題幹 / 配分 / 題型 / 選項快照、學員作答、該題得分 |

`_M` 只存**順序**（id 陣列），`_D` 存**內容**——`data-model` 明訂此拆法是為了「避免
`ET_QUIZ_ATTEMPT_M` 單筆過大」。

## 本模組不讀 `ET_QUESTION` / `ET_OPTION` 的當前值

僅在**建立 attempt 的那一刻**（`create_attempt`）讀一次以凍結快照。之後的取題、暫存、
閱卷、明細一律走 `_D` 的快照欄位——否則教師在學員作答期間改題會靜默改變計分。
"""

import json
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.attempt.rules import OptionSnapshot
from app.et.constants import ATTEMPT_IN_PROGRESS, GRADED_STATUSES
from app.et.course.models import EtChapter, EtItem
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM, EtQuizRetryReset

logger = logging.getLogger(__name__)


class EtAttemptRepository:
    """`ET_QUIZ_ATTEMPT_M` / `_D` 之讀寫，與作答次數之計算基準查詢。"""

    # ── 測驗與次數 ──────────────────────────────────────────────────────────

    async def get_quiz(self, db: AsyncSession, quiz_id: int) -> EtQuiz | None:
        return await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0))

    async def attempt_total(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> int:
        """該學員於該測驗之 attempt 總數。

        **不濾 `DELETED`**——本表 append-only、永不刪除（`data-model` §ET_QUIZ_ATTEMPT_M），
        且次數計算必須含全部歷史，否則「重置基準」對不起來。
        """
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtQuizAttemptM)
                .where(EtQuizAttemptM.user_id == user_id, EtQuizAttemptM.quiz_id == quiz_id)
            )
            or 0
        )

    async def reset_base(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> int:
        """`MAX(ATTEMPT_COUNT_AT_RESET)`；無重置紀錄時為 0（`data-model` 之公式）。"""
        return (
            await db.scalar(
                select(func.max(EtQuizRetryReset.attempt_count_at_reset)).where(
                    EtQuizRetryReset.user_id == user_id, EtQuizRetryReset.quiz_id == quiz_id
                )
            )
            or 0
        )

    async def score_summary(
        self, db: AsyncSession, *, user_id: str, quiz_id: int
    ) -> tuple[Decimal | None, Decimal | None, bool]:
        """`(最近一次分數, 最高分, 是否曾及格)`——引導頁用。

        最高分即**結業成績**（FR-ET-US6-10）。兩者一起回：只顯示最近一次會讓重考後
        考差的學員以為自己退步了，只顯示最高分則看不出本次表現。
        """
        rows = (
            await db.execute(
                select(EtQuizAttemptM.score, EtQuizAttemptM.is_pass, EtQuizAttemptM.attempt_no)
                .where(
                    EtQuizAttemptM.user_id == user_id,
                    EtQuizAttemptM.quiz_id == quiz_id,
                    EtQuizAttemptM.score.is_not(None),
                )
                .order_by(EtQuizAttemptM.attempt_no)
            )
        ).all()
        if not rows:
            return None, None, False
        scores = [r[0] for r in rows]
        return scores[-1], max(scores), any(r[1] for r in rows)

    # ── Attempt 生命週期 ────────────────────────────────────────────────────

    async def find_in_progress(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> EtQuizAttemptM | None:
        """未完成的作答（#279 SA Q1 裁示 A：續作而非作廢）。"""
        return await db.scalar(
            select(EtQuizAttemptM).where(
                EtQuizAttemptM.user_id == user_id,
                EtQuizAttemptM.quiz_id == quiz_id,
                EtQuizAttemptM.status == ATTEMPT_IN_PROGRESS,
                EtQuizAttemptM.deleted == 0,
            )
        )

    async def last_submitted_attempt_id(self, db: AsyncSession, *, user_id: str, quiz_id: int) -> int | None:
        """最近一次**已提交**的 attempt——引導頁的「查看上次作答明細」。

        取 `ATTEMPT_NO` 最大者而非 `SUBMITTED_AT`：續作的 attempt 可能比後開的先提交，
        而「上次」對學員的意思是「上一次作答」，那是次序不是時間。

        狀態以**白名單**篩（與 `service.result` 同一組），不用 `!= IN_PROGRESS`——否則新增
        狀態時這裡會開始回傳一個 `result` 拒絕的 id，前端就得到一顆按了必 404 的按鈕。
        """
        return await db.scalar(
            select(EtQuizAttemptM.attempt_id)
            .where(
                EtQuizAttemptM.user_id == user_id,
                EtQuizAttemptM.quiz_id == quiz_id,
                EtQuizAttemptM.status.in_(GRADED_STATUSES),
                EtQuizAttemptM.deleted == 0,
            )
            .order_by(EtQuizAttemptM.attempt_no.desc())
            .limit(1)
        )

    async def get_attempt(self, db: AsyncSession, attempt_id: int) -> EtQuizAttemptM | None:
        return await db.scalar(
            select(EtQuizAttemptM).where(EtQuizAttemptM.attempt_id == attempt_id, EtQuizAttemptM.deleted == 0)
        )

    async def create_attempt(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        course_id: int,
        quiz: EtQuiz,
        attempt_no: int,
        question_order: list[int],
        option_order: dict[int, list[int]],
        questions: list[EtQuestion],
        options_by_question: dict[int, list[EtOption]],
        operator: OperatorInfo,
    ) -> EtQuizAttemptM:
        """建立 attempt 並**凍結全部快照**——這是本 issue 唯一讀題目當前值的地方。

        `_M` 存順序（id 陣列的 JSON），`_D` 逐題存內容。兩者一起寫在同一個交易裡，
        否則會出現「有順序但沒有題目內容」的 attempt，而那種 attempt 打開就是白畫面。
        """
        now = utcnow()
        attempt = EtQuizAttemptM(
            user_id=user_id,
            course_id=course_id,
            quiz_id=quiz.quiz_id,
            attempt_no=attempt_no,
            started_at=now,
            status=ATTEMPT_IN_PROGRESS,
            question_order=json.dumps(question_order),
            option_order=json.dumps({str(k): v for k, v in option_order.items()}),
            pass_score_snapshot=quiz.pass_score,
            time_limit_snapshot=quiz.time_limit_min,
            created_user=operator.user_id,
            created_date=now,
        )
        db.add(attempt)
        await db.flush()

        by_id = {q.question_id: q for q in questions}
        db.add_all(
            [
                EtQuizAttemptD(
                    attempt_id=attempt.attempt_id,
                    question_id=qid,
                    stem_snapshot=by_id[qid].stem,
                    points_snapshot=by_id[qid].points,
                    type_snapshot=by_id[qid].question_type,
                    # 依洗牌後的順序凍結——`option_order` 已是該題的呈現順序
                    options_snapshot=json.dumps(
                        [
                            {"option_id": o.option_id, "text": o.option_text, "is_correct": o.is_correct}
                            for o in _ordered(options_by_question[qid], option_order[qid])
                        ],
                        ensure_ascii=False,
                    ),
                    selected_options=None,
                    created_user=operator.user_id,
                    created_date=now,
                )
                for qid in question_order
            ]
        )
        await db.flush()
        return attempt

    async def list_details(self, db: AsyncSession, attempt_id: int) -> list[EtQuizAttemptD]:
        """該次 attempt 的逐題明細。

        **不濾 `DELETED`**：#279 SA 裁示 Q2 = C 之後，刪除題目不再連帶軟刪除本表，
        故正常情況下不會有 `DELETED=1` 的列；保留不濾是為了讓「歷次永久可回看」在
        任何殘留資料下都成立（例如裁示前既有的資料）。
        """
        rows = await db.scalars(select(EtQuizAttemptD).where(EtQuizAttemptD.attempt_id == attempt_id))
        return list(rows)

    async def save_answer(
        self, db: AsyncSession, *, attempt_id: int, question_id: int, selected: list[int], operator: OperatorInfo
    ) -> bool:
        """暫存單題作答；回傳該題是否存在於此 attempt。

        以 `UPDATE ... WHERE` 一次完成——先查再寫會在快速連點時產生無意義的競態，
        而暫存是**覆寫**語意（`UQ(ATTEMPT_ID, QUESTION_ID)`），本來就冪等。
        """
        from sqlalchemy import update

        result = await db.execute(
            update(EtQuizAttemptD)
            .where(EtQuizAttemptD.attempt_id == attempt_id, EtQuizAttemptD.question_id == question_id)
            .values(
                selected_options=json.dumps(selected),
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount > 0

    async def submit(
        self,
        db: AsyncSession,
        *,
        attempt: EtQuizAttemptM,
        status: str,
        total: Decimal,
        is_pass: bool,
        per_question: dict[int, Decimal],
        submitted_at: datetime,
        operator: OperatorInfo,
    ) -> bool:
        """寫入閱卷結果（逐題得分 + 主檔總分與狀態）；回傳是否真的由本次完成轉移。

        主檔以**條件式 UPDATE**（`WHERE STATUS = IN_PROGRESS`）轉移狀態並檢查 `rowcount`。
        先在記憶體比對狀態再無條件寫回的話，兩個並行的 `submit` 都會通過檢查，後寫的一方
        會用自己讀到的答案覆蓋分數——`SELECTED_OPTIONS` 與 `SCORE` 因此可能對不起來，而
        `ET_QUIZ_ATTEMPT_D` 正是本模組不寫稽核日誌時唯一的追溯來源。
        """
        from sqlalchemy import update

        moved = await db.execute(
            update(EtQuizAttemptM)
            .where(EtQuizAttemptM.attempt_id == attempt.attempt_id, EtQuizAttemptM.status == ATTEMPT_IN_PROGRESS)
            .values(
                status=status,
                score=total,
                is_pass=is_pass,
                submitted_at=submitted_at,
                updated_user=operator.user_id,
                updated_date=submitted_at,
            )
        )
        if moved.rowcount == 0:
            return False

        for question_id, score in per_question.items():
            await db.execute(
                update(EtQuizAttemptD)
                .where(EtQuizAttemptD.attempt_id == attempt.attempt_id, EtQuizAttemptD.question_id == question_id)
                .values(score=score, updated_user=operator.user_id, updated_date=submitted_at)
            )
        await db.flush()
        # 讓呼叫端手上的 ORM 物件與剛寫入的值一致（回應直接讀它）
        attempt.status = status
        attempt.score = total
        attempt.is_pass = is_pass
        attempt.submitted_at = submitted_at
        return True

    # ── 授權反查：**一條鏈推導，不拼裝**（比照 #274 `progress/repository`）────────

    async def quiz_context(self, db: AsyncSession, quiz_id: int) -> tuple[int, int] | None:
        """測驗 → `(所屬項目, 所屬課程)`；任一跳被軟刪除或**引用不唯一**時回 `None`。

        測驗本體不帶 `COURSE_ID`——它是被 `ET_ITEM` 引用的，授權一定要經過那一跳。
        兩個值由同一次查詢得出，避免「A 課的課程 + B 課的項目」這種拼裝結果。
        """
        rows = await db.execute(
            select(EtItem.item_id, EtChapter.course_id)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtItem.quiz_id == quiz_id, EtItem.deleted == 0, EtChapter.deleted == 0)
        )
        found = rows.all()
        if len(found) != 1:
            if len(found) > 1:
                # fail-closed 是對的（不拼裝 A 課課程 + B 課項目），但它會讓該測驗的
                # 五個端點全部永久 404 而畫面上毫無線索。至少留一筆可追查的訊號。
                logger.warning("測驗 %s 被 %d 個章節項目引用，授權反查無法定案", quiz_id, len(found))
            return None
        return found[0][0], found[0][1]

    # ── 建立 attempt 時所需的題目來源（唯一一處讀當前值）────────────────────

    async def list_questions(self, db: AsyncSession, quiz_id: int) -> list[EtQuestion]:
        rows = await db.scalars(
            select(EtQuestion)
            .where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0)
            .order_by(EtQuestion.sort_order, EtQuestion.question_id)
        )
        return list(rows)

    async def options_by_question(self, db: AsyncSession, question_ids: list[int]) -> dict[int, list[EtOption]]:
        if not question_ids:
            return {}
        rows = await db.scalars(
            select(EtOption)
            .where(EtOption.question_id.in_(question_ids), EtOption.deleted == 0)
            .order_by(EtOption.sort_order, EtOption.option_id)
        )
        grouped: dict[int, list[EtOption]] = {qid: [] for qid in question_ids}
        for option in rows:
            grouped[option.question_id].append(option)
        return grouped


def _ordered(options: list[EtOption], order: list[int]) -> list[EtOption]:
    """依 `order` 指定的 id 順序排列選項；不在 `order` 內者附於末尾（防禦性）。"""
    by_id = {o.option_id: o for o in options}
    ordered = [by_id[oid] for oid in order if oid in by_id]
    ordered.extend(o for o in options if o.option_id not in set(order))
    return ordered


def parse_options_snapshot(raw: str) -> list[OptionSnapshot]:
    """`OPTIONS_SNAPSHOT` JSON → 計分用的 `OptionSnapshot`。"""
    return [
        OptionSnapshot(option_id=o["option_id"], text=o["text"], is_correct=o["is_correct"]) for o in json.loads(raw)
    ]


def parse_selected(raw: str | None) -> list[int]:
    """`SELECTED_OPTIONS` JSON → id 清單；`None` / 空字串視為未作答。"""
    return json.loads(raw) if raw else []
