"""課程「活表內容樹」的單一遍歷（#631）。

## 為何抽成共用的一支

兩個地方要走這棵樹，而且**必須對「哪些列算課程內容」給出完全相同的答案**：

| 用途 | 在哪 |
|---|---|
| seed：活表 → 暫存區 | `stage_repository.seed_from_live` |
| 刪除偵測：活表有而暫存沒有 ⇒ 教師刪了它 | `stage_apply` |

各寫一份的失效方式最難發現：若**只有 seed 漏搬**某一種，刪除偵測會把它判成「教師
刪了它」而在按下「更新」時連帶軟刪——教師沒做過那個動作，資料卻不見了。共用同一支
之後，漏掉一種的後果退化為「那種內容不版本化」（兩邊一致地看不到它），方向安全得多。

⚠️ 遍歷是**手寫**的，不是由 `APPLY_ORDER` 泛型推導：父子關係有兩種方向
（`ET_ITEM.MATERIAL_ID` 反向指著教材），泛型版比手寫更難讀，而這段的正確性全靠人
看得懂。`test_種出的樹涵蓋十一種實體` 是漏掉一種時唯一會紅的地方。
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.catalog.models import EtCourseTag
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE,
    ENTITY_COURSE_TAG,
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
)
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz
from app.et.survey.models import EtSurvey, EtSurveyOption, EtSurveyQuestion

#: `(ENTITY_TYPE, 活表 PK)`——跨型別唯一的鍵（不同表的 PK 會撞號）。
LiveKey = tuple[str, int]


@dataclass(frozen=True)
class LiveNode:
    """活表內容樹的一個節點。

    Attributes:
        entity_type: `stage_rules.ENTITY_*` 之一。
        row: 活表 model 實例（供取欄位值）。
        key: 本節點的 `LiveKey`。
        parent_key: 父節點的 `LiveKey`；`None` ＝ 掛在課程下（章節與問卷）。
        sort_order: 同層排序；本身沒有排序欄位者（教材、測驗）為 0。
    """

    entity_type: str
    row: Any
    key: LiveKey
    parent_key: LiveKey | None
    sort_order: int


async def load_live_tree(db: AsyncSession, course_id: int) -> tuple[LiveNode, ...]:
    """載入課程的活表內容樹，**父節點必定排在子節點之前**。

    ⚠️ **不濾問卷的 `is_active`**——停用的問卷仍是課程內容，教師可以再啟用它。
    「停用視同沒有問卷」是**檢核**那一層的判斷（`stage_rules._survey_question_count`），
    不是遍歷這一層的。濾掉會讓它在按「更新」時被判成「教師刪了它」而連帶軟刪。
    """
    nodes: list[LiveNode] = []

    # 🔴 課程本體與受訓對象（#720）。**暫存樹是森林、不是單一棵樹**：課程、章節、
    # 問卷都是根（`parent_key is None`），`COURSE` 底下只掛受訓對象。
    #
    # 不把章節改掛到課程之下，是為了把改動面壓到最小——`stage_rules._roots()` 本來就
    # 同時以 `entity_type` 過濾，重新掛親會動到那裡與 `stage_apply._validate_tree`，
    # 而那兩處是 #631 的核心路徑。
    #
    # ⛔ `stage_apply._delete_removed` **必須永不刪課程節點**：它以「活表有、暫存沒有」
    # 判定教師刪了它，而刪課程是另一條路徑（草稿專用），不經暫存。
    course = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))
    if course is not None:
        course_key = (ENTITY_COURSE, course.course_id)
        nodes.append(LiveNode(ENTITY_COURSE, course, course_key, None, 0))
        for tag in await db.scalars(
            select(EtCourseTag)
            .where(EtCourseTag.course_id == course_id, EtCourseTag.deleted == 0)
            .order_by(EtCourseTag.course_tag_id)
        ):
            nodes.append(LiveNode(ENTITY_COURSE_TAG, tag, (ENTITY_COURSE_TAG, tag.course_tag_id), course_key, 0))

    chapters = list(
        await db.scalars(
            select(EtChapter)
            .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
            .order_by(EtChapter.sort_order)
        )
    )
    for chapter in chapters:
        ch_key = (ENTITY_CHAPTER, chapter.chapter_id)
        nodes.append(LiveNode(ENTITY_CHAPTER, chapter, ch_key, None, chapter.sort_order))
        await _walk_items(db, chapter, ch_key, nodes)

    await _walk_survey(db, course_id, nodes)
    return tuple(nodes)


async def _walk_items(db: AsyncSession, chapter: EtChapter, ch_key: LiveKey, nodes: list[LiveNode]) -> None:
    items = list(
        await db.scalars(
            select(EtItem)
            .where(EtItem.chapter_id == chapter.chapter_id, EtItem.deleted == 0)
            .order_by(EtItem.sort_order)
        )
    )
    for item in items:
        item_key = (ENTITY_ITEM, item.item_id)
        nodes.append(LiveNode(ENTITY_ITEM, item, item_key, ch_key, item.sort_order))
        if item.item_type == ITEM_MATERIAL and item.material_id:
            await _walk_material(db, item.material_id, item_key, nodes)
        elif item.item_type == ITEM_QUIZ and item.quiz_id:
            await _walk_quiz(db, item.quiz_id, item_key, nodes)


async def _walk_material(db: AsyncSession, material_id: int, item_key: LiveKey, nodes: list[LiveNode]) -> None:
    material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_id, EtMaterial.deleted == 0))
    if material is None:
        # 孤兒項目（教材已軟刪、項目還在）。唯一的刪除路徑會連項目一起刪，故今天不可達；
        # 真的出現時**不中斷遍歷**——那門課本來就不該通過檢核，`BLOCK_ITEM_NO_TITLE` 會以
        # 空名稱擋下（同 `publish_repository._item_titles` 對同一情形的處理）。
        return
    mat_key = (ENTITY_MATERIAL, material.material_id)
    nodes.append(LiveNode(ENTITY_MATERIAL, material, mat_key, item_key, 0))
    for video in await db.scalars(
        select(EtMaterialVideo)
        .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
        .order_by(EtMaterialVideo.sort_order)
    ):
        nodes.append(
            LiveNode(ENTITY_MATERIAL_VIDEO, video, (ENTITY_MATERIAL_VIDEO, video.video_id), mat_key, video.sort_order)
        )
    for doc in await db.scalars(
        select(EtMaterialDoc)
        .where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
        .order_by(EtMaterialDoc.sort_order)
    ):
        nodes.append(LiveNode(ENTITY_MATERIAL_DOC, doc, (ENTITY_MATERIAL_DOC, doc.mat_doc_id), mat_key, doc.sort_order))


async def _walk_quiz(db: AsyncSession, quiz_id: int, item_key: LiveKey, nodes: list[LiveNode]) -> None:
    quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id, EtQuiz.deleted == 0))
    if quiz is None:
        return  # 同 `_walk_material` 的孤兒情形
    quiz_key = (ENTITY_QUIZ, quiz.quiz_id)
    nodes.append(LiveNode(ENTITY_QUIZ, quiz, quiz_key, item_key, 0))
    for question in await db.scalars(
        select(EtQuestion).where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0).order_by(EtQuestion.sort_order)
    ):
        q_key = (ENTITY_QUESTION, question.question_id)
        nodes.append(LiveNode(ENTITY_QUESTION, question, q_key, quiz_key, question.sort_order))
        for option in await db.scalars(
            select(EtOption)
            .where(EtOption.question_id == question.question_id, EtOption.deleted == 0)
            .order_by(EtOption.sort_order)
        ):
            nodes.append(LiveNode(ENTITY_OPTION, option, (ENTITY_OPTION, option.option_id), q_key, option.sort_order))


async def _walk_survey(db: AsyncSession, course_id: int, nodes: list[LiveNode]) -> None:
    survey = await db.scalar(select(EtSurvey).where(EtSurvey.course_id == course_id, EtSurvey.deleted == 0))
    if survey is None:
        return
    s_key = (ENTITY_SURVEY, survey.survey_id)
    nodes.append(LiveNode(ENTITY_SURVEY, survey, s_key, None, 0))
    for sq in await db.scalars(
        select(EtSurveyQuestion)
        .where(EtSurveyQuestion.survey_id == survey.survey_id, EtSurveyQuestion.deleted == 0)
        .order_by(EtSurveyQuestion.sort_order)
    ):
        sq_key = (ENTITY_SURVEY_QUESTION, sq.sq_id)
        nodes.append(LiveNode(ENTITY_SURVEY_QUESTION, sq, sq_key, s_key, sq.sort_order))
        for so in await db.scalars(
            select(EtSurveyOption)
            .where(EtSurveyOption.sq_id == sq.sq_id, EtSurveyOption.deleted == 0)
            .order_by(EtSurveyOption.sort_order)
        ):
            nodes.append(LiveNode(ENTITY_SURVEY_OPTION, so, (ENTITY_SURVEY_OPTION, so.so_id), sq_key, so.sort_order))
