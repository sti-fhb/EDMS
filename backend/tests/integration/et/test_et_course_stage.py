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
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ, QUESTION_SINGLE, ROLE_TEACHER, SURVEY_QUESTION_SINGLE
from app.et.course.models import EtCourse, EtCourseContentStage, EtItem
from app.et.course.publish_repository import EtPublishRepository
from app.et.course.publish_rules import evaluate_publish
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
from app.et.material.models import EtMaterialDoc, EtMaterialVideo
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

        await repo.clear(db, cid, _operator(uid))

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
        await repo.clear(db, cid, _operator(uid))

        await repo.seed_from_live(db, cid, _operator(uid))

        assert {n.entity_type for n in await repo.load_tree(db, cid)} == _ALL_TYPES

    async def test_沒有暫存區時_has_stage_為假(self, client, db) -> None:
        """正向錨點：少了這條，`has_stage` 恆回 True 也會讓上面兩條通過。"""
        uid = await _user(db, "ZT_S11")
        cid = await _full_course(client, db, uid)

        assert await EtCourseStageRepository().has_stage(db, cid) is False
