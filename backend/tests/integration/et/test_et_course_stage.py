"""已發布課程編輯暫存區的 seed / load / clear（#631）。

純規則（暫存樹 → `CourseSnapshot`）與對照表已由 `tests/unit/et/test_et_course_stage*.py`
以 unit 涵蓋。這裡只驗需要真 DB 才驗得了的事：

1. **seed 的遍歷有沒有漏搬某一種實體**——那段是手寫的（父子關係有兩種方向，泛型遍歷
   更難讀），漏一種的症狀是靜默的：教師編了那種東西、按「更新」沒生效
2. **seed 搬得忠不忠實**——以「暫存樹組出的檢核結果 == 活表組出的檢核結果」驗證
3. 軟刪除的內容不得被搬進暫存
4. 清空是軟刪除，且清空後可以再次 seed（唯一索引帶 `DELETED = 0`）
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ, QUESTION_SINGLE, ROLE_TEACHER, SURVEY_QUESTION_SINGLE
from app.et.course.models import EtChapter, EtCourse, EtCourseContentStage, EtItem
from app.et.course.publish_repository import EtPublishRepository
from app.et.course.publish_rules import evaluate_publish
from app.et.course.stage_apply import _DELETED_WITH_ITEM, _DELETERS, apply_stage
from app.et.course.stage_entities import SPEC_BY_TYPE, payload_fields
from app.et.course.stage_repository import EtCourseStageRepository
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
    to_course_snapshot,
)
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz
from app.et.roles.models import EtUserRole
from app.et.survey.models import EtSurvey, EtSurveyOption, EtSurveyQuestion
from tests.integration.et._tag_pairs import all_units_id

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_ALL_TYPES = {
    ENTITY_CHAPTER,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_VIDEO,
    ENTITY_MATERIAL_DOC,
    ENTITY_QUIZ,
    ENTITY_QUESTION,
    ENTITY_OPTION,
    ENTITY_SURVEY,
    ENTITY_SURVEY_QUESTION,
    ENTITY_SURVEY_OPTION,
}


def _operator(user_id: str) -> OperatorInfo:
    return OperatorInfo(user_id=user_id)


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"測試{user_id}",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


async def _attach_tag(db, course_id: int) -> None:
    now = utcnow()
    tag = EtTag(
        tag_name=f"標籤{course_id}",
        is_active=True,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=now,
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    db.add(
        EtCourseTag(
            unit_tag_id=await all_units_id(db),
            course_id=course_id,
            tag_id=tag.tag_id,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _full_course(client, db, uid: str) -> int:
    """建一門**十一種實體全部具備**的課程。

    🔴 「全部具備」是刻意的：`test_種出的樹涵蓋十一種實體` 要靠它才驗得到漏搬。
    少建任何一種，那條測試會因為「活表本來就沒有」而假性通過。
    """
    now = utcnow().replace(microsecond=0)
    created = await client.post(
        _COURSES,
        json={
            "course_name": "暫存區測試課程",
            "open_start_at": (now - timedelta(days=1)).isoformat(),
            "open_end_at": (now + timedelta(days=30)).isoformat(),
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    await _attach_tag(db, cid)

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    chapter_id = ch.json()["chapter_id"]

    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材甲"},
        headers=_bearer(uid),
    )
    assert mat.status_code == 201, mat.text
    material_id = mat.json()["material_id"]

    quiz = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考"},
        headers=_bearer(uid),
    )
    assert quiz.status_code == 201, quiz.text
    await client.post(
        f"/api/et/quizzes/{quiz.json()['quiz_id']}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "題幹",
            "points": 100,
            "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
        },
        headers=_bearer(uid),
    )

    # 影片、文件引用與問卷直接建列——本檔要驗的是 seed 有沒有搬到它們，
    # 不是上傳與問卷 API 本身（那些各自有測試）。
    audit = {"created_user": uid, "created_date": now, "deleted": 0}
    db.add(
        EtMaterialVideo(
            material_id=material_id,
            file_path="et/v/1.mp4",
            file_name="1.mp4",
            duration_sec=90,
            file_size_bytes=1024,
            sort_order=1,
            **audit,
        )
    )
    db.add(EtMaterialDoc(material_id=material_id, doc_id="DM-TRAINING-000001", sort_order=1, **audit))
    survey = EtSurvey(course_id=cid, survey_name="課後問卷", is_active=True, version=0, **audit)
    db.add(survey)
    await db.flush()
    sq = EtSurveyQuestion(
        survey_id=survey.survey_id,
        question_type=SURVEY_QUESTION_SINGLE,
        stem="滿意度",
        sort_order=1,
        version=0,
        **audit,
    )
    db.add(sq)
    await db.flush()
    db.add(EtSurveyOption(sq_id=sq.sq_id, option_text="很滿意", sort_order=1, **audit))
    await db.flush()
    return cid


async def _stage_rows(db, course_id: int) -> list[EtCourseContentStage]:
    rows = await db.scalars(
        select(EtCourseContentStage)
        .where(EtCourseContentStage.course_id == course_id)
        .order_by(EtCourseContentStage.stage_id)
    )
    return list(rows.all())


class TestSeedCoverage:
    async def test_種出的樹涵蓋十一種實體(self, client, db) -> None:
        """🔴 seed 的遍歷是手寫的，漏一種的症狀是**靜默**的。

        教師編了那種東西、按「更新」沒生效，而且沒有任何錯誤訊息——因為「活表有而
        暫存沒有」會被套用端解讀成「教師刪了它」，那一刀下去還會連帶把它軟刪掉。
        """
        uid = await _user(db, "ZT_S1")
        cid = await _full_course(client, db, uid)

        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))

        assert {n.entity_type for n in await EtCourseStageRepository().load_tree(db, cid)} == _ALL_TYPES

    async def test_父子關係以_parent_stage_id_串接(self, client, db) -> None:
        """巢狀五層：章節 → 項目 → 測驗 → 題目 → 選項，每一層都指得到父層。"""
        uid = await _user(db, "ZT_S2")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()

        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = {n.stage_id: n for n in await repo.load_tree(db, cid)}

        option = next(n for n in nodes.values() if n.entity_type == ENTITY_OPTION)
        question = nodes[option.parent_stage_id]
        quiz = nodes[question.parent_stage_id]
        item = nodes[quiz.parent_stage_id]
        chapter = nodes[item.parent_stage_id]

        assert [question.entity_type, quiz.entity_type, item.entity_type, chapter.entity_type] == [
            ENTITY_QUESTION,
            ENTITY_QUIZ,
            ENTITY_ITEM,
            ENTITY_CHAPTER,
        ]
        assert chapter.parent_stage_id is None, "章節掛在課程下"

    async def test_每一列都記下了來源_id(self, client, db) -> None:
        """seed 出來的全部是「既有內容」，`SOURCE_ID` 不得為 `None`——
        `None` 的語意是「新增的、活表還沒有」，套用時會再插一列重複的。"""
        uid = await _user(db, "ZT_S3")
        cid = await _full_course(client, db, uid)

        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))

        assert all(n.source_id is not None for n in await EtCourseStageRepository().load_tree(db, cid))


class TestSeedFidelity:
    async def test_暫存樹與活表組出相同的檢核結果(self, client, db) -> None:
        """🥇 本檔最重要的一條：seed 搬得忠不忠實。

        兩邊的識別碼**刻意不同**（暫存用 `STAGE_ID`，活表用內容表 PK），所以比的是
        結構與缺漏代碼，不是物件相等。
        """
        uid = await _user(db, "ZT_S4")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))

        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        live = await EtPublishRepository().snapshot(db, course)
        staged = to_course_snapshot(
            await repo.load_tree(db, cid),
            status=course.status,
            open_start_at=course.open_start_at,
            open_end_at=course.open_end_at,
            tag_count=live.tag_count,
        )

        assert staged.chapter_count == live.chapter_count
        assert [c.item_count for c in staged.chapters] == [c.item_count for c in live.chapters]
        assert [i.title for i in staged.items] == [i.title for i in live.items]
        assert [(q.question_count, q.points_total) for q in staged.quizzes] == [
            (q.question_count, q.points_total) for q in live.quizzes
        ]
        assert staged.material_count == live.material_count
        assert staged.doc_ids == live.doc_ids
        assert staged.survey_question_count == live.survey_question_count
        assert {b.code for b in evaluate_publish(staged, obsolete_doc_ids=frozenset())} == {
            b.code for b in evaluate_publish(live, obsolete_doc_ids=frozenset())
        }

    async def test_配分被完整搬進_payload(self, client, db) -> None:
        """正向錨點：「改配分後總分不再是 100」是 issue 列的四個症狀之一。

        上一條比的是**彙總後**的 `points_total`，看不出單題配分是否逐題搬對。
        """
        uid = await _user(db, "ZT_S5")
        cid = await _full_course(client, db, uid)
        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))

        question = next(
            n for n in await EtCourseStageRepository().load_tree(db, cid) if n.entity_type == ENTITY_QUESTION
        )

        assert question.payload["points"] == 100
        assert question.payload["stem"] == "題幹"

    async def test_payload_只含內容欄位(self, client, db) -> None:
        """⛔ 不得搬 PK、排序、樂觀鎖與稽核欄位——搬了會在套用時蓋回舊值。"""
        uid = await _user(db, "ZT_S6")
        cid = await _full_course(client, db, uid)
        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))

        for row in await _stage_rows(db, cid):
            keys = set(json.loads(row.payload))
            assert keys == set(payload_fields(SPEC_BY_TYPE[row.entity_type])), row.entity_type
            assert not keys & {"version", "deleted", "created_user", "created_date", "sort_order"}

    async def test_停用的問卷也會被搬進暫存(self, client, db) -> None:
        """⚠️ seed **不濾** `is_active`：停用的問卷仍是課程內容，教師可以再啟用它。

        「停用視同沒有問卷」是**檢核**那一層的判斷，不是搬運這一層的。漏搬會讓它在
        按下「更新」時被當成「活表有而暫存沒有」而連帶刪掉——而那是不可逆的。
        """
        uid = await _user(db, "ZT_S7")
        cid = await _full_course(client, db, uid)
        survey = await db.scalar(select(EtSurvey).where(EtSurvey.course_id == cid))
        survey.is_active = False
        await db.flush()

        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))
        nodes = await EtCourseStageRepository().load_tree(db, cid)

        staged_survey = [n for n in nodes if n.entity_type == ENTITY_SURVEY]
        assert len(staged_survey) == 1, "停用的問卷仍須搬進暫存"
        assert staged_survey[0].payload["is_active"] is False
        assert [n for n in nodes if n.entity_type == ENTITY_SURVEY_QUESTION], "其題目也要一起搬"

    async def test_軟刪除的內容不搬(self, client, db) -> None:
        uid = await _user(db, "ZT_S8")
        cid = await _full_course(client, db, uid)
        quiz_item = await db.scalar(select(EtItem).where(EtItem.quiz_id.is_not(None)))
        quiz_item.deleted = 1
        await db.flush()

        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))
        types = {n.entity_type for n in await EtCourseStageRepository().load_tree(db, cid)}

        assert ENTITY_QUIZ not in types, "項目軟刪後其測驗不該被搬"
        assert ENTITY_MATERIAL in types, "其他項目不受影響"


class TestClear:
    async def test_清空是軟刪除(self, client, db) -> None:
        """⛔ 專案禁硬刪除。暫存區是暫時資料，但仍照規範走 `DELETED = 1`。"""
        uid = await _user(db, "ZT_S9")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        before = len(await _stage_rows(db, cid))

        await repo.clear(db, cid, _operator(uid), stage_ids=[n.stage_id for n in await repo.load_tree(db, cid)])

        assert before > 0
        assert len(await _stage_rows(db, cid)) == before, "列還在（軟刪），不是被硬刪"
        assert await repo.load_tree(db, cid) == (), "但讀不到了"
        assert await repo.has_stage(db, cid) is False

    async def test_清空後可以再次_seed(self, client, db) -> None:
        """🔴 唯一索引 `(COURSE_ID, ENTITY_TYPE, SOURCE_ID)` 的條件帶 `DELETED = 0`。

        少了那個條件，已軟刪的列會繼續佔住鍵，第二次編輯同一門課就永遠撞鍵——
        與 `ET_MATERIAL_DOC` / `ET_ITEM` 踩過的是同一個坑。
        """
        uid = await _user(db, "ZT_S10")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        await repo.clear(db, cid, _operator(uid), stage_ids=[n.stage_id for n in await repo.load_tree(db, cid)])

        await repo.seed_from_live(db, cid, _operator(uid))

        assert {n.entity_type for n in await repo.load_tree(db, cid)} == _ALL_TYPES

    async def test_沒有暫存區時_has_stage_為假(self, client, db) -> None:
        """正向錨點：少了這條，`has_stage` 恆回 True 也會讓上面兩條通過。"""
        uid = await _user(db, "ZT_S11")
        cid = await _full_course(client, db, uid)

        assert await EtCourseStageRepository().has_stage(db, cid) is False


# ── 套用：暫存樹 → 活表 ────────────────────────────────────────────────────────


async def _stage_node(
    db, course_id: int, entity_type: str, uid: str, *, parent: int | None, sort_order: int, **payload
):
    """直接建一列「新增的」暫存（`SOURCE_ID` 為 `None`）。

    PR 1 還沒把編輯端的 28 個寫入端點導向暫存區（那是 PR 2），所以這裡自己造。
    """
    row = EtCourseContentStage(
        course_id=course_id,
        entity_type=entity_type,
        source_id=None,
        parent_stage_id=parent,
        sort_order=sort_order,
        payload=json.dumps(payload, ensure_ascii=False),
        created_user=uid,
        created_date=utcnow(),
        deleted=0,
    )
    db.add(row)
    await db.flush()
    return row.stage_id


async def _drop_stage(db, course_id: int, entity_type: str) -> None:
    """把某型別的暫存列全部移除——模擬教師刪掉那些內容。"""
    await db.execute(
        update(EtCourseContentStage)
        .where(
            EtCourseContentStage.course_id == course_id,
            EtCourseContentStage.entity_type == entity_type,
            EtCourseContentStage.deleted == 0,
        )
        .values(deleted=1)
    )
    await db.flush()


async def _drop_subtree(db, nodes, root_stage_id: int) -> None:
    """把某節點與其整棵子樹移出暫存——模擬教師刪掉那一塊。

    🔴 **必須連子樹一起刪**：只刪中間一層會讓子節點的 `PARENT_STAGE_ID` 落空，
    那是編輯端不可能產生的畸形樹，`apply_stage` 的驗證會當場擋下
    （見 `test_父參照斷鏈時明確報錯`）。
    """
    subtree = {root_stage_id}
    for _ in range(5):  # 巢狀最深 5 層
        subtree |= {n.stage_id for n in nodes if n.parent_stage_id in subtree}
    await db.execute(update(EtCourseContentStage).where(EtCourseContentStage.stage_id.in_(subtree)).values(deleted=1))
    await db.flush()


async def _set_payload(db, stage_id: int, payload: dict) -> None:
    await db.execute(
        update(EtCourseContentStage)
        .where(EtCourseContentStage.stage_id == stage_id)
        .values(payload=json.dumps(payload, ensure_ascii=False))
    )
    await db.flush()


async def _live_chapters(db, course_id: int) -> list[EtChapter]:
    rows = await db.scalars(
        select(EtChapter).where(EtChapter.course_id == course_id, EtChapter.deleted == 0).order_by(EtChapter.sort_order)
    )
    return list(rows.all())


async def _apply(db, course_id: int, uid: str) -> None:
    repo = EtCourseStageRepository()
    course = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
    await apply_stage(db, course=course, nodes=await repo.load_tree(db, course_id), operator=_operator(uid))


class TestApplyInsertAndUpdate:
    async def test_未編輯時套用不改變任何東西(self, client, db) -> None:
        """seed 後立刻套用 ＝ 把活表寫回它自己。**這是整個機制的恆等律**。

        不成立的話，教師只要進編輯頁再按「更新」就會動到內容——而那種漂移沒有任何
        畫面會提示。
        """
        uid = await _user(db, "ZT_A1")
        cid = await _full_course(client, db, uid)
        before = [(c.chapter_id, c.chapter_name, c.sort_order) for c in await _live_chapters(db, cid)]
        await EtCourseStageRepository().seed_from_live(db, cid, _operator(uid))

        await _apply(db, cid, uid)

        assert [(c.chapter_id, c.chapter_name, c.sort_order) for c in await _live_chapters(db, cid)] == before

    async def test_暫存裡改的欄位套用後才生效(self, client, db) -> None:
        uid = await _user(db, "ZT_A2")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        node = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        await _set_payload(db, node.stage_id, {"chapter_name": "改過的章名"})
        assert (await _live_chapters(db, cid))[0].chapter_name == "第一章", "套用前活表不得變動"

        await _apply(db, cid, uid)

        assert (await _live_chapters(db, cid))[0].chapter_name == "改過的章名"

    async def test_改配分套用後生效(self, client, db) -> None:
        """issue 列的四個症狀之一：已發布後改配分，總分不再是 100。"""
        uid = await _user(db, "ZT_A3")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        q = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_QUESTION)
        await _set_payload(db, q.stage_id, {**q.payload, "points": 55})

        await _apply(db, cid, uid)

        live = await db.scalar(select(EtQuestion).where(EtQuestion.question_id == q.source_id))
        assert live.points == 55

    async def test_巢狀新增五層一次套用(self, client, db) -> None:
        """🔴 新章節 → 新項目 → 新測驗 → 新題目 → 新選項，套用前**全部都沒有活表 id**。

        `PARENT_STAGE_ID` 自參照讓它們用暫存列的 PK 互相指，套用時才一層層換成真 id。
        """
        uid = await _user(db, "ZT_A4")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))

        ch = await _stage_node(db, cid, ENTITY_CHAPTER, uid, parent=None, sort_order=9, chapter_name="全新章節")
        item = await _stage_node(db, cid, ENTITY_ITEM, uid, parent=ch, sort_order=1, item_type=ITEM_QUIZ)
        quiz = await _stage_node(
            db,
            cid,
            ENTITY_QUIZ,
            uid,
            parent=item,
            sort_order=0,
            quiz_name="全新測驗",
            description=None,
            pass_score=80,
            time_limit_min=None,
            max_retry=3,
        )
        question = await _stage_node(
            db,
            cid,
            ENTITY_QUESTION,
            uid,
            parent=quiz,
            sort_order=1,
            question_type=QUESTION_SINGLE,
            stem="新題",
            points=100,
        )
        await _stage_node(db, cid, ENTITY_OPTION, uid, parent=question, sort_order=1, option_text="甲", is_correct=True)

        await _apply(db, cid, uid)

        chapters = await _live_chapters(db, cid)
        assert [c.chapter_name for c in chapters] == ["第一章", "全新章節"]
        new_item = await db.scalar(
            select(EtItem).where(EtItem.chapter_id == chapters[1].chapter_id, EtItem.deleted == 0)
        )
        assert new_item is not None and new_item.quiz_id is not None, "項目的反向連結要指到新建的測驗"
        assert new_item.material_id is None, "測驗型項目不得同時帶教材（CK_ET_ITEM_TYPE_TARGET）"
        new_quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == new_item.quiz_id))
        assert new_quiz.quiz_name == "全新測驗"
        new_q = await db.scalar(select(EtQuestion).where(EtQuestion.quiz_id == new_quiz.quiz_id))
        assert new_q.stem == "新題"
        assert await db.scalar(select(EtOption).where(EtOption.question_id == new_q.question_id)) is not None


class TestApplyOrdering:
    async def test_對調兩個章節的順序不撞唯一鍵(self, client, db) -> None:
        """🔴 部分唯一索引是**非 deferrable**、逐列即時檢核。

        少了「先移到負數暫存區」那一階段，對調會在中途撞鍵——而對調順序是最常見的
        編輯動作之一。
        """
        uid = await _user(db, "ZT_A5")
        cid = await _full_course(client, db, uid)
        await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid))
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        chapters = [n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER]
        assert len(chapters) == 2
        for node, new_order in zip(chapters, [2, 1], strict=True):
            await db.execute(
                update(EtCourseContentStage)
                .where(EtCourseContentStage.stage_id == node.stage_id)
                .values(sort_order=new_order)
            )
        await db.flush()

        await _apply(db, cid, uid)

        assert [c.chapter_name for c in await _live_chapters(db, cid)] == ["第二章", "第一章"]

    async def test_刪掉第一章後第二章遞補成第一不撞鍵(self, client, db) -> None:
        """🔴 這條釘住**刪除排在寫入之前**。

        反過來的話，第二章要寫進 `SORT_ORDER = 1` 時，第一章還佔著那個槽。
        """
        uid = await _user(db, "ZT_A6")
        cid = await _full_course(client, db, uid)
        await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid))
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        first = next(n for n in nodes if n.entity_type == ENTITY_CHAPTER and n.payload["chapter_name"] == "第一章")
        second = next(n for n in nodes if n.entity_type == ENTITY_CHAPTER and n.payload["chapter_name"] == "第二章")
        await _drop_subtree(db, nodes, first.stage_id)
        await db.execute(
            update(EtCourseContentStage).where(EtCourseContentStage.stage_id == second.stage_id).values(sort_order=1)
        )
        await db.flush()

        await _apply(db, cid, uid)

        assert [(c.chapter_name, c.sort_order) for c in await _live_chapters(db, cid)] == [("第二章", 1)]


class TestApplyDelete:
    async def test_移除的內容是軟刪不是硬刪(self, client, db) -> None:
        uid = await _user(db, "ZT_A7")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        doc_before = await db.scalar(select(EtMaterialDoc).where(EtMaterialDoc.deleted == 0))
        await _drop_stage(db, cid, ENTITY_MATERIAL_DOC)

        await _apply(db, cid, uid)

        after = await db.scalar(select(EtMaterialDoc).where(EtMaterialDoc.mat_doc_id == doc_before.mat_doc_id))
        assert after is not None, "⛔ 不得硬刪"
        assert after.deleted == 1

    async def test_刪掉整個項目時教材一起被刪(self, client, db) -> None:
        """教材不在 `_DELETERS` 裡——它隨所屬項目一起被 cascade 刪掉。

        ⚠️ 若日後支援「一個教材被多個項目重用」，這個前提就不再成立，本條會紅——
        那時要做的是改刪除策略，不是刪掉這條測試。
        """
        uid = await _user(db, "ZT_A8")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        material = next(n for n in nodes if n.entity_type == ENTITY_MATERIAL)
        await _drop_subtree(db, nodes, material.parent_stage_id)

        await _apply(db, cid, uid)

        live = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material.source_id))
        assert live.deleted == 1, "教材隨項目一起被軟刪"
        assert ENTITY_MATERIAL not in _DELETERS, "⛔ 不得為教材另設單獨的刪除路徑"

    async def test_父參照斷鏈時明確報錯(self, client, db) -> None:
        """🔴 少了驗證，斷鏈會在解析父層時變成 `KeyError: <某個數字>`。

        那種樹編輯端不可能產生，出現就代表有人繞過編輯端直接動暫存表——此時要的是
        一個說得出「哪個節點指向哪裡」的錯誤，而不是寫到一半才爆。
        """
        uid = await _user(db, "ZT_A11")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        material = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_MATERIAL)
        # 只刪中間那一層，讓它的影片 / 文件子節點父參照落空
        await db.execute(
            update(EtCourseContentStage).where(EtCourseContentStage.stage_id == material.stage_id).values(deleted=1)
        )
        await db.flush()

        with pytest.raises(AppError, match="父參照斷鏈"):
            await _apply(db, cid, uid)

    async def test_刪除項目時委派既有_cascade(self, client, db) -> None:
        """🔴 `EtItemRepository.soft_delete_with_cascade` 還處理學員進度與完課戳記。

        自己在套用端寫一份軟刪會漏掉那些，而漏掉不會報錯。
        """
        uid = await _user(db, "ZT_A9")
        cid = await _full_course(client, db, uid)
        item = await db.scalar(select(EtItem).where(EtItem.quiz_id.is_not(None), EtItem.deleted == 0))
        db.add(
            EtProgress(
                user_id=uid,
                course_id=cid,
                item_id=item.item_id,
                is_completed=True,
                created_user=uid,
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        quiz_item = next(n for n in nodes if n.entity_type == ENTITY_ITEM and n.source_id == item.item_id)
        await _drop_subtree(db, nodes, quiz_item.stage_id)

        await _apply(db, cid, uid)

        progress = await db.scalar(select(EtProgress).where(EtProgress.item_id == item.item_id))
        assert progress.deleted == 1, "學員進度要跟著軟刪——那是既有 cascade 做的事"


class TestForeignKeysSurvive:
    async def test_套用後學員進度仍指向同一個項目(self, client, db) -> None:
        """🥇 **整個設計方向的立論基礎**。

        學員資料對內容表有 7 條硬外鍵（`ET_PROGRESS.ITEM_ID`、
        `ET_QUIZ_ATTEMPT_D.QUESTION_ID` 等）。「編輯中版本用新的列、生效時整組換掉」
        做不到，正是因為換列等於換 id、那 7 條會全部斷線。

        本方案不換 id：既有內容列**原地更新**，id 跨「更新」保持不變。這條測試是
        那個主張唯一的執行點。
        """
        uid = await _user(db, "ZT_A10")
        cid = await _full_course(client, db, uid)
        item = await db.scalar(select(EtItem).where(EtItem.material_id.is_not(None), EtItem.deleted == 0))
        db.add(
            EtProgress(
                user_id=uid,
                course_id=cid,
                item_id=item.item_id,
                is_completed=True,
                created_user=uid,
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        # 改點東西，確保套用真的有寫入（否則「id 沒變」可能只是因為什麼都沒做）
        ch = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        await _set_payload(db, ch.stage_id, {"chapter_name": "改名了"})

        await _apply(db, cid, uid)

        progress = await db.scalar(select(EtProgress).where(EtProgress.user_id == uid))
        assert progress.item_id == item.item_id, "項目 id 不得因為「更新」而改變"
        assert progress.deleted == 0 and progress.is_completed is True
        assert (await _live_chapters(db, cid))[0].chapter_name == "改名了", "套用確實有寫入"


class TestDeleterCoverage:
    def test_每一種可刪除的型別都有刪除路徑(self) -> None:
        """少一個的症狀是套用時 `KeyError`——會爆，但要等到有人真的刪了那種東西。"""
        assert set(_DELETERS) | _DELETED_WITH_ITEM == _ALL_TYPES


# ── 「更新」端點 ───────────────────────────────────────────────────────────────

_APPLY = "/api/et/courses/{cid}/content/apply"


async def _publish(client, db, uid: str, cid: int) -> None:
    """把課程推到已發布——「更新」只對已發布 / 已關閉課程有意義。"""
    r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    await db.flush()


class TestUpdateEndpoint:
    async def test_暫存區為空時是安全的_no_op(self, client, db) -> None:
        """教師沒做任何編輯就按「更新」——不該回 422，也不該寫稽核。

        對一門內容未變的課程回錯誤，會讓教師以為自己弄壞了什麼。
        """
        uid = await _user(db, "ZT_U1")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        assert r.status_code == 200, r.text
        assert r.json() == {"course_id": cid, "applied_count": 0}

    async def test_檢核通過後暫存內容一次生效且暫存區清空(self, client, db) -> None:
        """AC 1 / AC 3：按「更新」前學員端看不到變化，按下後一次看到全部。"""
        uid = await _user(db, "ZT_U2")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        ch = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        await _set_payload(db, ch.stage_id, {"chapter_name": "更新後的章名"})
        assert (await _live_chapters(db, cid))[0].chapter_name == "第一章", "按下更新前活表不得變動"

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        assert r.status_code == 200, r.text
        assert r.json()["applied_count"] > 0
        assert (await _live_chapters(db, cid))[0].chapter_name == "更新後的章名"
        assert await repo.has_stage(db, cid) is False, "生效後暫存區要清空"

    async def test_檢核未通過時回_422_且活表一行都沒動(self, client, db) -> None:
        """🥇 **AC 2 的核心**：不通過時學員端維持上一版。

        ⚠️ **本條驗的是結果，不是順序。** 保證來自「檢核與套用在同一個交易」——而那表示
        「檢核先跑、沒套用」與「套用了但隨 422 一起回滾」對外**不可區分**，兩者都滿足
        AC 2。想把順序本身釘住，只能在 service 層以 unit 驗（`apply_stage` 未被呼叫），
        那留給 PR 2 連同編輯端一起做。

        這裡刻意同時改了章名：證明**不只是被擋下的那一項**，連同一批的其他變更也不生效。
        """
        uid = await _user(db, "ZT_U3")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        # 把測驗的題目全部刪掉 ⇒ 0 題測驗，應被 BLOCK_QUIZ_NO_QUESTION 擋下
        question = next(n for n in nodes if n.entity_type == ENTITY_QUESTION)
        await _drop_subtree(db, nodes, question.stage_id)
        # 同時改章名，用來證明「不通過時連別的變更也不會生效」
        ch = next(n for n in nodes if n.entity_type == ENTITY_CHAPTER)
        await _set_payload(db, ch.stage_id, {"chapter_name": "不該生效的章名"})

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error_code"] == "ET_PUBLISH_001"
        assert "QUIZ_NO_QUESTION" in {b["code"] for b in body["blockers"]}
        assert (await _live_chapters(db, cid))[0].chapter_name == "第一章", "未通過時其他變更也不得生效"
        live_q = await db.scalar(select(EtQuestion).where(EtQuestion.question_id == question.source_id))
        assert live_q.deleted == 0, "未通過時題目不得被刪"

    async def test_缺漏指向的是暫存節點(self, client, db) -> None:
        """`target_id` 要能讓前端在編輯頁上標出紅框，而編輯頁讀的是暫存樹。

        回活表 id 的話，新增的內容無從定位、既有內容則指向畫面上不存在的號碼——
        兩個號碼空間會重疊，所以回錯了不會爆、只會標錯區塊。
        """
        uid = await _user(db, "ZT_U4")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        quiz = next(n for n in nodes if n.entity_type == ENTITY_QUIZ)
        question = next(n for n in nodes if n.entity_type == ENTITY_QUESTION)
        await _drop_subtree(db, nodes, question.stage_id)

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        blocker = next(b for b in r.json()["blockers"] if b["code"] == "QUIZ_NO_QUESTION")
        assert blocker["target_id"] == quiz.stage_id
        assert blocker["target_id"] != quiz.source_id, "⚠️ 兩個號碼空間會重疊，這條才分得出來"

    async def test_草稿課程不走更新(self, client, db) -> None:
        """草稿沒有學員、內容不需版本化，它的生效入口是「發布」。"""
        uid = await _user(db, "ZT_U5")
        cid = await _full_course(client, db, uid)

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_COURSE_010"

    async def test_非擁有者不得更新(self, client, db) -> None:
        uid = await _user(db, "ZT_U6")
        other = await _user(db, "ZT_U7")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)

        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(other))

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_查無課程回_404(self, client, db) -> None:
        uid = await _user(db, "ZT_U8")

        r = await client.post(_APPLY.format(cid=99999999), headers=_bearer(uid))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_COURSE_001"

    async def test_更新與發布跑的是同一組檢核(self, client, db) -> None:
        """🥇 四個動作共用 `evaluate_publish` ——各自複製一份必然分岔，而分岔的症狀是
        「更新擋下了發布會放行的課程」，沒有錯誤訊息。

        做法：對同一份壞掉的內容，比對 `publish-check`（走活表）與「更新」（走暫存樹）
        回的缺漏代碼集合。
        """
        uid = await _user(db, "ZT_U9")
        cid = await _full_course(client, db, uid)
        await _publish(client, db, uid, cid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        question = next(n for n in nodes if n.entity_type == ENTITY_QUESTION)
        await _drop_subtree(db, nodes, question.stage_id)
        # 活表那側也弄成同樣的狀態，兩邊才比得起來
        await db.execute(update(EtQuestion).where(EtQuestion.question_id == question.source_id).values(deleted=1))
        await db.flush()

        # ⚠️ **會失敗的那一支一定要放最後**：422 會讓該請求所屬交易回滾，連上面以
        # `db` 寫入但尚未 commit 的前置資料一起（見 `sti-testing` 的「失敗請求回滾前置
        # 資料」）。順序寫反的症狀是 `publish-check` 看到一份已被還原的活表而回空集合。
        check = await client.get(f"{_COURSES}/{cid}/publish-check", headers=_bearer(uid))
        check_codes = {b["code"] for b in check.json()["blockers"]}
        r = await client.post(_APPLY.format(cid=cid), headers=_bearer(uid))

        assert check_codes == {"QUIZ_NO_QUESTION"}, "前置要真的弄壞了活表那側"
        assert {b["code"] for b in r.json()["blockers"]} == check_codes


# ── Code review（2026-10-14）指出的四個缺陷，各配一條測試 ──────────────────────


class TestReviewFindings:
    async def test_payload_缺欄位時不覆寫活表既有值(self, client, db) -> None:
        """🔴 HIGH：`payload_fields` 是推導的，內容表日後加欄位會自動納入，但**編輯到
        一半、尚未更新的既有暫存列**沒有那個 key。

        原本用 `.get()`，缺 key 會把 `None` 明確寫進去——nullable 欄位於是被**靜默**
        清成 NULL（教師：「我填過的說明按更新就不見了」），NOT NULL 欄位則拋
        IntegrityError。正確語意是「這列產生時還沒有這個欄位」，保留活表當前值。

        本條以「把既有 payload 的某個 key 拿掉」模擬那個情境。
        """
        uid = await _user(db, "ZT_R1")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        # 先給教材一段說明，才驗得出它有沒有被清掉
        material = await db.scalar(select(EtMaterial).where(EtMaterial.deleted == 0))
        material.description_html = "<p>原本的說明</p>"
        await db.flush()
        await repo.seed_from_live(db, cid, _operator(uid))
        node = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_MATERIAL)
        # 模擬「這列是舊版程式寫的，還沒有 description_html 這個 key」
        await _set_payload(db, node.stage_id, {"material_name": node.payload["material_name"]})

        await _apply(db, cid, uid)

        live = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == node.source_id))
        assert live.description_html == "<p>原本的說明</p>", "缺 key 不得被當成「清空」"
        assert live.material_name == node.payload["material_name"], "有 key 的照樣寫入"

    async def test_刪一項又增一項時不得蓋上完課戳記(self, client, db) -> None:
        """🔴 MEDIUM：刪除階段（階段 1）蓋章會用**中間狀態**判定完課。

        學員 2/3 完成，教師同一次更新刪掉未完成的那項**又新增一項**：階段 1 結束時
        是 2/2 被蓋章，階段 3 之後其實是 2/3、沒完課。而 `COMPLETED_AT` 只寫一次、
        回退不清除，那個時間戳會一直停在他沒完課的時點。

        修法是 `_DELETERS` 一律 `stamp=False`，整批套用完成後才蓋一次。
        """
        uid = await _user(db, "ZT_R2")
        cid = await _full_course(client, db, uid)
        items = list(await db.scalars(select(EtItem).where(EtItem.deleted == 0).order_by(EtItem.item_id)))
        assert len(items) == 2, "前置：教材項目與測驗項目各一"
        # 學員完成第一項、未完成第二項 ⇒ 1/2
        db.add(
            EtProgress(
                user_id=uid,
                course_id=cid,
                item_id=items[0].item_id,
                is_completed=True,
                created_user=uid,
                created_date=utcnow(),
                deleted=0,
            )
        )
        enrollment = EtEnrollment(
            user_id=uid,
            course_id=cid,
            join_source="MANUAL",
            joined_at=utcnow(),
            completion_status="IN_PROGRESS",
            is_removed=False,
            created_user=uid,
            created_date=utcnow(),
            deleted=0,
        )
        db.add(enrollment)
        await db.flush()

        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        # 刪掉未完成的那一項，同時新增一項 ⇒ 套用後仍是 1/2，沒完課
        doomed = next(n for n in nodes if n.entity_type == ENTITY_ITEM and n.source_id == items[1].item_id)
        await _drop_subtree(db, nodes, doomed.stage_id)
        chapter = next(n for n in nodes if n.entity_type == ENTITY_CHAPTER)
        new_item = await _stage_node(
            db, cid, ENTITY_ITEM, uid, parent=chapter.stage_id, sort_order=5, item_type=ITEM_MATERIAL
        )
        await _stage_node(
            db, cid, ENTITY_MATERIAL, uid, parent=new_item, sort_order=0, material_name="新教材", description_html=None
        )

        await _apply(db, cid, uid)

        after = await db.scalar(select(EtEnrollment).where(EtEnrollment.enrollment_id == enrollment.enrollment_id))
        assert after.completed_at is None, "套用後是 1/2，不該因為刪除階段的中間狀態被蓋章"

    async def test_暫存指向的活表列已被刪時整批失敗(self, client, db) -> None:
        """🔴 暫存期間活表列被別的路徑軟刪 ⇒ 整批失敗，不得部分寫入。

        ⭐ **擋下它的是歸屬守門，不是 rowcount 檢查。** code review 原本指出
        `_write` 命中 0 列時仍回傳 `source_id`（子節點會寫成指向已刪除的父層）；補了
        `_validate_tree` 的「`SOURCE_ID` 必須屬於本課程活表樹」之後，那一刀更早就落下
        ——被軟刪的列不在 `load_live_tree` 的結果裡。

        rowcount 檢查因此變成結構上不可達，但**刻意留著**（理由見 `_write` 的註解）。
        本條驗的是真正會發生的那個錯誤。
        """
        uid = await _user(db, "ZT_R3")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        node = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        # 模擬暫存期間該活表列被別的路徑軟刪
        await db.execute(update(EtChapter).where(EtChapter.chapter_id == node.source_id).values(deleted=1))
        await db.flush()

        with pytest.raises(AppError, match="不屬於本課程"):
            await _apply(db, cid, uid)

    async def test_清空只清載入過的那批(self, client, db) -> None:
        """🔴 HIGH 的後半：`clear` 原本是 `WHERE COURSE_ID = ?`。

        那會連「`load_tree` 之後才寫進來的編輯」一起清掉，而那筆編輯從來沒有被套用過
        ——教師的輸入**靜默消失**。改為只清呼叫端實際載入並套用的那批 `STAGE_ID`。
        """
        uid = await _user(db, "ZT_R4")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        loaded = await repo.load_tree(db, cid)
        chapter = next(n for n in loaded if n.entity_type == ENTITY_CHAPTER)
        # 模擬「套用途中教師又加了一章」
        latecomer = await _stage_node(db, cid, ENTITY_CHAPTER, uid, parent=None, sort_order=9, chapter_name="晚到的章")

        await repo.clear(db, cid, _operator(uid), stage_ids=[n.stage_id for n in loaded])

        remaining = {n.stage_id for n in await repo.load_tree(db, cid)}
        assert latecomer in remaining, "⛔ 沒被套用過的編輯不得被清掉"
        assert chapter.stage_id not in remaining, "載入過的那批照樣清掉"


class TestStructuralGuards:
    """`_validate_tree` 的四道結構不變式（2026-10-14 security review）。

    ⚠️ 這四道在本 PR 都**還不可達**——暫存列目前只由 `seed_from_live` 從本課程活表推導。
    它們是**為 PR 2 預留的**：編輯端一旦讓前端指定 `stage_id` / `source_id`，那幾條路就活了。

    ⛔ 不要因為「現在還到不了」而拿掉。補在這裡是一道結構守門；補在 12 個編輯端點各一次
    會漏，而漏掉的後果全都是靜默的。
    """

    async def test_指向別門課的活表資料時整批失敗(self, client, db) -> None:
        """🔴 最嚴重的那一道：`SOURCE_ID` 只要指得到任何一張內容表的活列就會被更新。

        沒有這道守門的話，一位教師可以覆寫**另一位教師**課程的章節 / 題目，而且
        `_upsert` 會把那些列改掛到他自己的課程底下（因為連結欄位會被重設）。

        本條以「把暫存列的 `SOURCE_ID` 改指向別門課的章節」重現。
        """
        uid = await _user(db, "ZT_G1")
        victim_uid = await _user(db, "ZT_G2")
        cid = await _full_course(client, db, uid)
        victim_cid = await _full_course(client, db, victim_uid)
        victim_chapter = await db.scalar(
            select(EtChapter).where(EtChapter.course_id == victim_cid, EtChapter.deleted == 0)
        )
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        mine = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id == mine.stage_id)
            .values(source_id=victim_chapter.chapter_id)
        )
        await db.flush()

        with pytest.raises(AppError, match="不屬於本課程"):
            await _apply(db, cid, uid)

        after = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == victim_chapter.chapter_id))
        assert after.course_id == victim_cid, "⛔ 別人的章節不得被改掛到本課程"
        assert after.chapter_name == victim_chapter.chapter_name

    async def test_未知的實體型別整批失敗(self, client, db) -> None:
        """少了這道，那個節點會被三個階段**全部略過**——教師編了、按更新沒生效，
        而且不會有任何錯誤訊息，最後還被 `clear` 當成已套用而清掉。"""
        uid = await _user(db, "ZT_G3")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        node = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_CHAPTER)
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id == node.stage_id)
            .values(entity_type="PODCAST")
        )
        await db.flush()

        with pytest.raises(AppError, match="未知的 ENTITY_TYPE"):
            await _apply(db, cid, uid)

    async def test_該有父層卻沒有時整批失敗(self, client, db) -> None:
        """🔴 項目若無父層會拿到 `chapter_id = course_id`。

        11 張表的 identity **號碼空間重疊**，那個 id 通常真的存在某一列，而
        `FK_ET_ITEM_CHAPTER` 只要求 `CHAPTER_ID` 存在、不要求它屬於本課程——
        於是項目被靜默塞進**別門課**的章節。
        """
        uid = await _user(db, "ZT_G4")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        item = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_ITEM)
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id == item.stage_id)
            .values(parent_stage_id=None)
        )
        await db.flush()

        with pytest.raises(AppError, match="父層有無與對照表不符"):
            await _apply(db, cid, uid)

    async def test_父層型別不符時整批失敗(self, client, db) -> None:
        """題目掛在章節底下之類的錯配。多數情況會被 FK 擋成錯誤，但那是靠巧合不是靠設計。"""
        uid = await _user(db, "ZT_G5")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))
        nodes = await repo.load_tree(db, cid)
        question = next(n for n in nodes if n.entity_type == ENTITY_QUESTION)
        chapter = next(n for n in nodes if n.entity_type == ENTITY_CHAPTER)
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id == question.stage_id)
            .values(parent_stage_id=chapter.stage_id)
        )
        await db.flush()

        with pytest.raises(AppError, match="父層型別為"):
            await _apply(db, cid, uid)

    async def test_正常的暫存樹不被守門擋下(self, client, db) -> None:
        """正向錨點：少了這條，讓 `_validate_tree` 無條件拋錯也會讓上面四條通過。"""
        uid = await _user(db, "ZT_G6")
        cid = await _full_course(client, db, uid)
        repo = EtCourseStageRepository()
        await repo.seed_from_live(db, cid, _operator(uid))

        await _apply(db, cid, uid)

        assert (await _live_chapters(db, cid))[0].chapter_name == "第一章"
