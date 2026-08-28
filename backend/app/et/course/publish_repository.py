"""ET 發布檢核所需之課程結構彙總查詢（US3 / #204）。

單獨成檔而非併入 `repository.py`：那裡已是 459 行的四個 Repository，而本模組只服務
「發布」這一件事，且查詢形狀（跨章節 / 項目 / 教材 / 測驗的彙總）與那裡的逐實體
CRUD 性質不同。

## 設計要點：一次查完，交給純函式判斷

所有查詢在此做完並組成 `CourseSnapshot`，判斷全部交給 `publish_rules.evaluate_publish`。
這樣六項檢核的所有組合都能以 unit test 涵蓋，不必為「沒有章節」「配分 90」「引用了
廢止文件」各建一份真資料。

**不在此查 DM 廢止狀態**——那是跨模組 I/O，須經 `app/services` 之 `DmDocumentService`
（模組邊界），且逐一往外呼叫的節奏由 service 控制。本模組只回傳課程引用了哪些
`DOC_ID`。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.catalog.models import EtCourseTag
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.publish_rules import CourseSnapshot, QuizSummary
from app.et.material.models import EtMaterialDoc
from app.et.quiz.models import EtQuestion
from app.et.survey.models import EtSurvey, EtSurveyQuestion


class EtPublishRepository:
    """組出發布檢核所需之 `CourseSnapshot`。"""

    async def snapshot(self, db: AsyncSession, course: EtCourse) -> CourseSnapshot:
        """彙總課程結構。

        Args:
            course: 已取得之課程列（呼叫端已做過擁有者判定，此處不重查）。

        Returns:
            供 `evaluate_publish` 判斷之快照。
        """
        chapter_ids = await self._chapter_ids(db, course.course_id)
        return CourseSnapshot(
            status=course.status,
            open_start_at=course.open_start_at,
            open_end_at=course.open_end_at,
            tag_count=await self._tag_count(db, course.course_id),
            chapter_count=len(chapter_ids),
            material_count=await self._item_count(db, chapter_ids, ITEM_MATERIAL),
            quizzes=await self._quiz_summaries(db, chapter_ids),
            doc_ids=await self._doc_ids(db, chapter_ids),
            survey_question_count=await self._survey_question_count(db, course.course_id),
        )

    async def _survey_question_count(self, db: AsyncSession, course_id: int) -> int | None:
        """問卷題數；**沒有問卷時回 `None` 而非 0**。

        0 是「有問卷但一題都沒有」（要擋發布），`None` 是「沒有問卷」（選配，不擋）。
        兩者共用同一個值會讓 AC 23 失效——每一門沒建問卷的課程都會被擋住發布。
        """
        survey_id = await db.scalar(
            select(EtSurvey.survey_id).where(EtSurvey.course_id == course_id, EtSurvey.deleted == 0)
        )
        if survey_id is None:
            return None
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtSurveyQuestion)
                .where(EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0)
            )
            or 0
        )

    async def _chapter_ids(self, db: AsyncSession, course_id: int) -> list[int]:
        rows = await db.scalars(
            select(EtChapter.chapter_id).where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
        )
        return list(rows)

    async def _tag_count(self, db: AsyncSession, course_id: int) -> int:
        """課程已掛之受訓單位標籤數。

        以 `ET_COURSE_TAG` 的原始 table 計數而非查 `EtCourseTagRepository.list_tag_ids`——
        後者回傳 set 供編輯用，這裡只要數量。
        """
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtCourseTag)
                .where(EtCourseTag.course_id == course_id, EtCourseTag.deleted == 0)
            )
            or 0
        )

    async def _item_count(self, db: AsyncSession, chapter_ids: list[int], item_type: str) -> int:
        if not chapter_ids:
            return 0
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtItem)
                .where(
                    EtItem.chapter_id.in_(chapter_ids),
                    EtItem.item_type == item_type,
                    EtItem.deleted == 0,
                )
            )
            or 0
        )

    async def _quiz_summaries(self, db: AsyncSession, chapter_ids: list[int]) -> tuple[QuizSummary, ...]:
        """課程下每個測驗的題數與配分總和。

        以 `LEFT OUTER JOIN` 取題目——**0 題的測驗必須出現在結果裡**，那正是第六項
        檢核（`QUIZ_NO_QUESTION`，SA 裁示 #204 Q3）要抓的對象。用 INNER JOIN 會讓空
        測驗整個消失，檢核就永遠不會觸發，而測試若只用「有題目的測驗」建資料也看不
        出來。
        """
        if not chapter_ids:
            return ()
        rows = await db.execute(
            select(
                EtItem.quiz_id,
                func.count(EtQuestion.question_id),
                func.coalesce(func.sum(EtQuestion.points), 0),
            )
            .select_from(EtItem)
            .outerjoin(
                EtQuestion,
                (EtQuestion.quiz_id == EtItem.quiz_id) & (EtQuestion.deleted == 0),
            )
            .where(
                EtItem.chapter_id.in_(chapter_ids),
                EtItem.item_type == ITEM_QUIZ,
                EtItem.quiz_id.is_not(None),
                EtItem.deleted == 0,
            )
            .group_by(EtItem.quiz_id)
            .order_by(EtItem.quiz_id)
        )
        return tuple(
            QuizSummary(quiz_id=quiz_id, question_count=count, points_total=int(points))
            for quiz_id, count, points in rows.all()
        )

    async def _doc_ids(self, db: AsyncSession, chapter_ids: list[int]) -> frozenset[str]:
        """課程各教材引用之 DM 文件編號（去重）。

        去重是為了少問 DM 幾次——同一份文件被兩個教材引用時，廢止狀態只需查一次。
        """
        if not chapter_ids:
            return frozenset()
        rows = await db.scalars(
            select(EtMaterialDoc.doc_id)
            .select_from(EtItem)
            .join(EtMaterialDoc, EtMaterialDoc.material_id == EtItem.material_id)
            .where(
                EtItem.chapter_id.in_(chapter_ids),
                EtItem.item_type == ITEM_MATERIAL,
                EtItem.deleted == 0,
                EtMaterialDoc.deleted == 0,
            )
        )
        return frozenset(rows)
