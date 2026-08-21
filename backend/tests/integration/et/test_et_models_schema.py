"""ET 28 表 ORM 往返與關鍵約束測試（AC 1 強化）。

migration 能跑 ≠ schema 可用——本測試以**實際 ORM 寫入**走完整條關聯鏈
（課程 → 章節 → 項目 → 教材 → 影片 / 文件、測驗 → 題目 → 選項、選課 → 進度 →
影片進度 → 觀看區段、問卷 → 題目 → 選項 → 填答 → 明細、邀請 / 轉讓 / 週統計），
並驗證 DB 層真的擋得住違規資料（CHECK constraint、唯一約束）。

此舉同時涵蓋各 model 檔——它們原本在測試行程中從未被 import，coverage 為 0%。
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.et.constants import (
    ATTEMPT_SUBMITTED,
    COMPLETION_IN_PROGRESS,
    COURSE_DRAFT,
    INVITATION_PENDING,
    ITEM_MATERIAL,
    QUESTION_SINGLE,
    SOURCE_TAG_DEFAULT,
)
from app.et.course.models import EtChapter, EtCourse, EtItem, EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.invitation.models import EtInvitation, EtOwnerTransfer
from app.et.progress.models import EtEnrollment, EtProgress, EtProgressInterval, EtProgressVideo
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM, EtQuizRetryReset
from app.et.stats.models import EtWeeklyStat
from app.et.survey.models import (
    EtSurvey,
    EtSurveyOption,
    EtSurveyQuestion,
    EtSurveyResponseD,
    EtSurveyResponseM,
)

pytestmark = pytest.mark.integration

_U = "SCHEMA_U"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(**kw):
    """標準稽核欄位（一般業務表）。"""
    return {"created_user": _U, "created_date": _now(), "deleted": 0, **kw}


def _audit_ao(**kw):
    """append-only 表之稽核欄位（僅 CREATED_*）。"""
    return {"created_user": _U, "created_date": _now(), **kw}


async def _make_course(db, name="課程A") -> EtCourse:
    c = EtCourse(
        **_audit(
            course_name=name,
            status=COURSE_DRAFT,
            owner_id=_U,
            urgent_remind_sent=False,
            version=0,
            require_approval=False,
        )
    )
    db.add(c)
    await db.flush()
    return c


class TestCourseChain:
    async def test_課程到教材子表之完整寫入(self, db) -> None:
        course = await _make_course(db)
        ch = EtChapter(**_audit(course_id=course.course_id, chapter_name="第一章", sort_order=1, version=0))
        db.add(ch)
        mat = EtMaterial(**_audit(material_name="教材A", version=0))
        db.add(mat)
        await db.flush()

        db.add(
            EtMaterialVideo(
                **_audit(
                    material_id=mat.material_id,
                    file_path="/v/a.mp4",
                    file_name="a.mp4",
                    duration_sec=600,
                    file_size_bytes=1024,
                    sort_order=1,
                )
            )
        )
        db.add(EtMaterialDoc(**_audit(material_id=mat.material_id, doc_id="DM-TRAINING-000007", sort_order=1)))
        item = EtItem(
            **_audit(
                chapter_id=ch.chapter_id, item_type=ITEM_MATERIAL, sort_order=1, material_id=mat.material_id, version=0
            )
        )
        db.add(item)
        await db.flush()

        got = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.material_id == mat.material_id))
        assert got.duration_sec == 600, "覆蓋率分母須可正確往返"

    async def test_item_型別與目標互斥之_check_constraint_生效(self, db) -> None:
        """`ITEM_TYPE=MATERIAL` 卻掛 `QUIZ_ID`（或兩者皆空）須被 DB 擋下。"""
        course = await _make_course(db, "課程B")
        ch = EtChapter(**_audit(course_id=course.course_id, chapter_name="章", sort_order=1, version=0))
        db.add(ch)
        await db.flush()

        with pytest.raises((IntegrityError, DBAPIError)):
            await db.execute(
                text(
                    'INSERT INTO "ET_ITEM" ("CHAPTER_ID","ITEM_TYPE","SORT_ORDER","VERSION",'
                    '"CREATED_USER","CREATED_DATE","DELETED") VALUES (:c, :t, 1, 0, :u, :d, 0)'
                ),
                {"c": ch.chapter_id, "t": ITEM_MATERIAL, "u": _U, "d": _now()},
            )
        await db.rollback()

    async def test_邀請碼全域唯一(self, db) -> None:
        a = await _make_course(db, "課程C")
        a.invitation_code = "12345678"
        await db.flush()
        b = EtCourse(
            **_audit(
                course_name="課程D",
                status=COURSE_DRAFT,
                owner_id=_U,
                urgent_remind_sent=False,
                version=0,
                require_approval=False,
                invitation_code="12345678",
            )
        )
        db.add(b)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


class TestQuizChain:
    async def test_測驗到作答明細與重考重置(self, db) -> None:
        course = await _make_course(db, "課程E")
        quiz = EtQuiz(**_audit(quiz_name="測驗A", pass_score=80, max_retry=3, version=0))
        db.add(quiz)
        await db.flush()
        q = EtQuestion(
            **_audit(
                quiz_id=quiz.quiz_id, question_type=QUESTION_SINGLE, stem="題幹", points=100, sort_order=1, version=0
            )
        )
        db.add(q)
        await db.flush()
        db.add(EtOption(**_audit(question_id=q.question_id, option_text="選項1", is_correct=True, sort_order=1)))

        att = EtQuizAttemptM(
            **_audit(
                user_id=_U,
                course_id=course.course_id,
                quiz_id=quiz.quiz_id,
                attempt_no=1,
                started_at=_now(),
                status=ATTEMPT_SUBMITTED,
                question_order="[1]",
                option_order="[[1]]",
                pass_score_snapshot=80,
                time_limit_snapshot=None,
            )
        )
        db.add(att)
        await db.flush()
        db.add(
            EtQuizAttemptD(
                **_audit(
                    attempt_id=att.attempt_id,
                    question_id=q.question_id,
                    stem_snapshot="題幹",
                    points_snapshot=100,
                    type_snapshot=QUESTION_SINGLE,
                    options_snapshot="[]",
                )
            )
        )
        db.add(
            EtQuizRetryReset(
                **_audit_ao(
                    user_id=_U,
                    quiz_id=quiz.quiz_id,
                    course_id=course.course_id,
                    attempt_count_at_reset=1,
                    executed_by=_U,
                    executed_at=_now(),
                )
            )
        )
        await db.flush()

        assert att.time_limit_snapshot is None, "不限時之測驗須可存 NULL 快照"

    async def test_同一測驗之作答次序唯一(self, db) -> None:
        course = await _make_course(db, "課程F")
        quiz = EtQuiz(**_audit(quiz_name="測驗B", pass_score=80, max_retry=3, version=0))
        db.add(quiz)
        await db.flush()
        base = dict(
            user_id=_U,
            course_id=course.course_id,
            quiz_id=quiz.quiz_id,
            started_at=_now(),
            status=ATTEMPT_SUBMITTED,
            question_order="[]",
            option_order="[]",
            pass_score_snapshot=80,
        )
        db.add(EtQuizAttemptM(**_audit(attempt_no=1, **base)))
        await db.flush()
        db.add(EtQuizAttemptM(**_audit(attempt_no=1, **base)))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


class TestProgressChain:
    async def test_選課到觀看區段(self, db) -> None:
        course = await _make_course(db, "課程G")
        ch = EtChapter(**_audit(course_id=course.course_id, chapter_name="章", sort_order=1, version=0))
        mat = EtMaterial(**_audit(material_name="教材", version=0))
        db.add_all([ch, mat])
        await db.flush()
        vid = EtMaterialVideo(
            **_audit(
                material_id=mat.material_id,
                file_path="/v/b.mp4",
                file_name="b.mp4",
                duration_sec=300,
                file_size_bytes=512,
                sort_order=1,
            )
        )
        db.add(vid)
        item = EtItem(
            **_audit(
                chapter_id=ch.chapter_id, item_type=ITEM_MATERIAL, sort_order=1, material_id=mat.material_id, version=0
            )
        )
        db.add(item)
        await db.flush()

        db.add(
            EtEnrollment(
                **_audit(
                    user_id=_U,
                    course_id=course.course_id,
                    join_source=SOURCE_TAG_DEFAULT,
                    joined_at=_now(),
                    completion_status=COMPLETION_IN_PROGRESS,
                    is_removed=False,
                )
            )
        )
        db.add(EtProgress(**_audit(user_id=_U, course_id=course.course_id, item_id=item.item_id, is_completed=False)))
        db.add(EtProgressVideo(**_audit(user_id=_U, video_id=vid.video_id, coverage_pct=0, last_position_sec=0)))
        # 每段播放一列——同一區間可重複，故刻意寫入兩列相同區段
        db.add(EtProgressInterval(**_audit(user_id=_U, video_id=vid.video_id, start_sec=0, end_sec=100)))
        db.add(EtProgressInterval(**_audit(user_id=_U, video_id=vid.video_id, start_sec=0, end_sec=100)))
        await db.flush()

        rows = await db.scalars(select(EtProgressInterval).where(EtProgressInterval.video_id == vid.video_id))
        assert len(rows.all()) == 2, "觀看區段不設唯一約束——重複觀看須能各自成列"


class TestSurveyChain:
    async def test_問卷到填答明細(self, db) -> None:
        course = await _make_course(db, "課程H")
        sv = EtSurvey(**_audit(course_id=course.course_id, survey_name="問卷", is_active=True, version=0))
        db.add(sv)
        await db.flush()
        sq = EtSurveyQuestion(**_audit(survey_id=sv.survey_id, stem="滿意度？", sort_order=1, version=0))
        db.add(sq)
        await db.flush()
        so = EtSurveyOption(**_audit(sq_id=sq.sq_id, option_text="滿意", sort_order=1))
        db.add(so)
        rm = EtSurveyResponseM(**_audit(survey_id=sv.survey_id, user_id=_U, submitted_at=_now()))
        db.add(rm)
        await db.flush()
        db.add(EtSurveyResponseD(**_audit(response_id=rm.response_id, sq_id=sq.sq_id, so_id=so.so_id)))
        await db.flush()

        # 一人一次：同問卷同使用者再填一次須被擋
        db.add(EtSurveyResponseM(**_audit(survey_id=sv.survey_id, user_id=_U, submitted_at=_now())))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async def test_一課程至多一份問卷(self, db) -> None:
        course = await _make_course(db, "課程I")
        db.add(EtSurvey(**_audit(course_id=course.course_id, survey_name="問卷1", is_active=True, version=0)))
        await db.flush()
        db.add(EtSurvey(**_audit(course_id=course.course_id, survey_name="問卷2", is_active=True, version=0)))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


class TestInvitationAndStats:
    async def test_邀請_轉讓_週統計(self, db) -> None:
        course = await _make_course(db, "課程J")
        db.add(
            EtInvitation(
                **_audit(
                    course_id=course.course_id,
                    email="a@example.com",
                    token_hash="h" * 64,
                    status=INVITATION_PENDING,
                    sent_at=_now(),
                    last_sent_at=_now(),
                )
            )
        )
        db.add(
            EtOwnerTransfer(
                **_audit_ao(
                    course_id=course.course_id,
                    from_owner_id=_U,
                    to_owner_id="OTHER",
                    reason="原教師離職",
                    executed_by=_U,
                    executed_at=_now(),
                )
            )
        )
        db.add(
            EtWeeklyStat(
                **_audit_ao(
                    course_id=course.course_id,
                    stat_date=date(2026, 8, 20),
                    avg_progress_pct=50,
                    cnt_not_started=1,
                    cnt_in_progress=2,
                    cnt_completed=3,
                    completion_rate=50,
                    cnt_enrolled=6,
                )
            )
        )
        await db.flush()

        got = await db.scalar(select(EtInvitation).where(EtInvitation.course_id == course.course_id))
        assert len(got.token_hash) == 64, "只存 SHA-256 雜湊、不存明文"

    async def test_週統計同課程同日唯一(self, db) -> None:
        course = await _make_course(db, "課程K")
        base = dict(
            course_id=course.course_id,
            stat_date=date(2026, 8, 21),
            avg_progress_pct=0,
            cnt_not_started=0,
            cnt_in_progress=0,
            cnt_completed=0,
            completion_rate=0,
            cnt_enrolled=0,
        )
        db.add(EtWeeklyStat(**_audit_ao(**base)))
        await db.flush()
        db.add(EtWeeklyStat(**_audit_ao(**base)))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
