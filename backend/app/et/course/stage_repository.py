"""已發布課程編輯暫存區的存取（#631）。

職責只有三件：**從活表種出整棵暫存樹**、**把暫存樹讀回來**、**清空**。
套用（暫存 → 活表）在 `stage_apply.py`；業務規則在 `stage_rules.py`（純函式）。

## 為何 seed 是「整棵複製」而不是「用到才複製」

暫存區存的是**完整的目標內容樹**，所以編輯端讀取就是直接讀它，不必把差異疊加回活表。
疊加邏輯會散落在 12 個讀取端點，而漏掉一處的症狀是**教師看不到自己剛做的編輯**。

代價是第一次編輯時多一次整棵複製。課程內容樹的量級是「章節 × 項目 × 題目」，
實務上數十到數百列，一次性成本可忽略。

## ⚠️ seed 的遍歷是**手寫**的，不是由 `APPLY_ORDER` 泛型推導

父子關係有兩種方向（`ET_ITEM.MATERIAL_ID` 反向指著教材），泛型遍歷寫出來比手寫更難讀，
而這段程式的正確性全靠人看得懂。代價是**新增內容型別時這裡會被漏掉**——
`test_種出的樹涵蓋十一種實體` 就是為此存在：少搬一種會紅。
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.models import EtChapter, EtCourseContentStage, EtItem
from app.et.course.stage_entities import SPEC_BY_TYPE, EntitySpec, payload_fields
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_DOC,
    ENTITY_MATERIAL_VIDEO,
    ENTITY_OPTION,
    ENTITY_QUESTION,
    ENTITY_QUIZ,
    ENTITY_SURVEY,
    ENTITY_SURVEY_OPTION,
    ENTITY_SURVEY_QUESTION,
    StageNode,
)
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz
from app.et.survey.models import EtSurvey, EtSurveyOption, EtSurveyQuestion


@dataclass(frozen=True)
class _SeedCtx:
    """一次 seed 期間共用的不變值。

    ⛔ 不放在 repository 實例上——本專案的 repository 一律無狀態，帶了狀態的那一份
    在同一請求內被重用時會用到上一次的操作者與時間戳。
    """

    course_id: int
    operator: OperatorInfo
    now: datetime


def to_payload(spec: EntitySpec, row: object) -> str:
    """把活表列的內容欄位序列化成 `PAYLOAD`。

    🔴 `json.dumps` 在遇到不可序列化的型別時會 `TypeError`——**那是刻意不接住的**。
    內容表若日後加了 `datetime` 之類的欄位，推導會自動把它納入 payload，而這裡會
    當場爆出來；靜默塞個字串進去才是真正的問題（套用時寫回活表會變成錯的型別）。
    """
    return json.dumps({f: getattr(row, f) for f in payload_fields(spec)}, ensure_ascii=False)


class EtCourseStageRepository:
    """暫存區的讀寫。"""

    async def has_stage(self, db: AsyncSession, course_id: int) -> bool:
        """該課程是否已有暫存區（＝教師已經開始編輯但還沒按「更新」）。"""
        found = await db.scalar(
            select(EtCourseContentStage.stage_id)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .limit(1)
        )
        return found is not None

    async def load_tree(self, db: AsyncSession, course_id: int) -> tuple[StageNode, ...]:
        """讀回整棵暫存樹（扁平，彼此以 `parent_stage_id` 串接）。"""
        rows = await db.scalars(
            select(EtCourseContentStage)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .order_by(EtCourseContentStage.stage_id)
        )
        return tuple(
            StageNode(
                stage_id=r.stage_id,
                entity_type=r.entity_type,
                source_id=r.source_id,
                parent_stage_id=r.parent_stage_id,
                sort_order=r.sort_order,
                payload=json.loads(r.payload),
            )
            for r in rows.all()
        )

    async def clear(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """清空暫存區。

        ⛔ **軟刪除**（`DELETED = 1`），遵專案禁硬刪規範。唯一索引的條件帶
        `DELETED = 0`，所以清空後再次編輯不會撞鍵。
        """
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def seed_from_live(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """把活表的內容樹整棵複製進暫存區。

        ⚠️ 呼叫端須先確認暫存區是空的——重複 seed 會被唯一索引擋下
        （`(COURSE_ID, ENTITY_TYPE, SOURCE_ID)`），那是正確的 fail-closed，但訊息不好讀。
        """
        ctx = _SeedCtx(course_id=course_id, operator=operator, now=utcnow())

        chapters = list(
            await db.scalars(
                select(EtChapter)
                .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
                .order_by(EtChapter.sort_order)
            )
        )
        for chapter in chapters:
            ch_stage = await self._add(db, ctx, ENTITY_CHAPTER, chapter, parent=None, sort_order=chapter.sort_order)
            await self._seed_items(db, ctx, chapter, ch_stage)

        await self._seed_survey(db, ctx)
        await db.flush()

    # ── 以下為 seed 的逐層遍歷 ────────────────────────────────────────────────

    async def _seed_items(self, db: AsyncSession, ctx: _SeedCtx, chapter: EtChapter, chapter_stage_id: int) -> None:
        items = list(
            await db.scalars(
                select(EtItem)
                .where(EtItem.chapter_id == chapter.chapter_id, EtItem.deleted == 0)
                .order_by(EtItem.sort_order)
            )
        )
        for item in items:
            item_stage = await self._add(
                db, ctx, ENTITY_ITEM, item, parent=chapter_stage_id, sort_order=item.sort_order
            )
            if item.item_type == ITEM_MATERIAL and item.material_id:
                await self._seed_material(db, ctx, item.material_id, item_stage)
            elif item.item_type == ITEM_QUIZ and item.quiz_id:
                await self._seed_quiz(db, ctx, item.quiz_id, item_stage)

    async def _seed_material(self, db: AsyncSession, ctx: _SeedCtx, material_id: int, item_stage_id: int) -> None:
        material = await db.scalar(
            select(EtMaterial).where(EtMaterial.material_id == material_id, EtMaterial.deleted == 0)
        )
        if material is None:
            # 孤兒項目（教材已軟刪、項目還在）。唯一的刪除路徑會連項目一起刪，故今天不可達；
            # 真的出現時**不中斷 seed**——那門課本來就不該通過檢核，`BLOCK_ITEM_NO_TITLE`
            # 會以空名稱擋下（同 `publish_repository._item_titles` 的處理）。
            return
        mat_stage = await self._add(db, ctx, ENTITY_MATERIAL, material, parent=item_stage_id, sort_order=0)
        for video in await db.scalars(
            select(EtMaterialVideo)
            .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
            .order_by(EtMaterialVideo.sort_order)
        ):
            await self._add(db, ctx, ENTITY_MATERIAL_VIDEO, video, parent=mat_stage, sort_order=video.sort_order)
        for doc in await db.scalars(
            select(EtMaterialDoc)
            .where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
            .order_by(EtMaterialDoc.sort_order)
        ):
            await self._add(db, ctx, ENTITY_MATERIAL_DOC, doc, parent=mat_stage, sort_order=doc.sort_order)

    async def _seed_quiz(self, db: AsyncSession, ctx: _SeedCtx, quiz_id: int, item_stage_id: int) -> None:
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0))
        if quiz is None:
            return  # 同 `_seed_material` 的孤兒情形
        quiz_stage = await self._add(db, ctx, ENTITY_QUIZ, quiz, parent=item_stage_id, sort_order=0)
        for question in await db.scalars(
            select(EtQuestion)
            .where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0)
            .order_by(EtQuestion.sort_order)
        ):
            q_stage = await self._add(
                db, ctx, ENTITY_QUESTION, question, parent=quiz_stage, sort_order=question.sort_order
            )
            for option in await db.scalars(
                select(EtOption)
                .where(EtOption.question_id == question.question_id, EtOption.deleted == 0)
                .order_by(EtOption.sort_order)
            ):
                await self._add(db, ctx, ENTITY_OPTION, option, parent=q_stage, sort_order=option.sort_order)

    async def _seed_survey(self, db: AsyncSession, ctx: _SeedCtx) -> None:
        """問卷。

        ⚠️ **不濾 `is_active`**——停用的問卷仍是課程內容的一部分，教師可以再啟用它。
        「停用視同沒有問卷」是**檢核**那一層的判斷（`stage_rules._survey_question_count`
        與活表那側的 `publish_repository._survey_question_count`），不是搬運這一層的。
        漏搬會讓停用的問卷在按下「更新」時被當成「活表有而暫存沒有」而連帶刪掉。
        """
        survey = await db.scalar(select(EtSurvey).where(EtSurvey.course_id == ctx.course_id, EtSurvey.deleted == 0))
        if survey is None:
            return
        s_stage = await self._add(db, ctx, ENTITY_SURVEY, survey, parent=None, sort_order=0)
        for sq in await db.scalars(
            select(EtSurveyQuestion)
            .where(EtSurveyQuestion.survey_id == survey.survey_id, EtSurveyQuestion.deleted == 0)
            .order_by(EtSurveyQuestion.sort_order)
        ):
            sq_stage = await self._add(db, ctx, ENTITY_SURVEY_QUESTION, sq, parent=s_stage, sort_order=sq.sort_order)
            for so in await db.scalars(
                select(EtSurveyOption)
                .where(EtSurveyOption.sq_id == sq.sq_id, EtSurveyOption.deleted == 0)
                .order_by(EtSurveyOption.sort_order)
            ):
                await self._add(db, ctx, ENTITY_SURVEY_OPTION, so, parent=sq_stage, sort_order=so.sort_order)

    async def _add(
        self, db: AsyncSession, ctx: _SeedCtx, entity_type: str, row: object, *, parent: int | None, sort_order: int
    ) -> int:
        """新增一列暫存並回傳其 `STAGE_ID`（供子層當 `PARENT_STAGE_ID`）。"""
        spec = SPEC_BY_TYPE[entity_type]
        stage = EtCourseContentStage(
            course_id=ctx.course_id,
            entity_type=entity_type,
            source_id=getattr(row, spec.pk),
            parent_stage_id=parent,
            sort_order=sort_order,
            payload=to_payload(spec, row),
            created_user=ctx.operator.user_id,
            created_date=ctx.now,
        )
        db.add(stage)
        # 🔴 **必須當場 flush**：子層要拿它的 `STAGE_ID` 當父參照，而那是 Identity 欄位，
        # 不 flush 取不到。
        await db.flush()
        return stage.stage_id


def nodes_by_type(nodes: Sequence[StageNode], entity_type: str) -> list[StageNode]:
    """測試與套用端共用的小工具。"""
    return [n for n in nodes if n.entity_type == entity_type]
