"""ET03 學員學習狀況追蹤整合測試（US9 / #322）。

此處只驗**需要真 DB 才驗得了**的事：跨表聚合（完課數 / 總項目數 / 最高分平均）、
軟刪除過濾、以及「死欄位不可讀」這類只有真資料才會暴露的問題。

純推導（`can_reset_retry`、完課三態）於 `tests/unit/et/test_tracking_rules.py`。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.users.models import DpUser
from app.et.constants import (
    ATTEMPT_IN_PROGRESS,
    ATTEMPT_SUBMITTED,
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    COMPLETION_NOT_STARTED,
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
    SURVEY_QUESTION_SINGLE,
    SURVEY_QUESTION_TEXT,
)
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuiz, EtQuizAttemptM, EtQuizRetryReset
from app.et.roles.models import EtUserRole
from app.et.survey.models import (
    EtSurvey,
    EtSurveyOption,
    EtSurveyQuestion,
    EtSurveyResponseD,
    EtSurveyResponseM,
)

pytestmark = pytest.mark.integration


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, roles: tuple[str, ...] = (ROLE_TEACHER,), name: str | None = None) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=name or f"測試{user_id}",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    for role in roles:
        db.add(
            EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
        )
    await db.flush()
    return user_id


async def _course(db, *, owner: str, name: str = "追蹤測試課程") -> int:
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=COURSE_PUBLISHED,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=now + timedelta(days=30),
        version=0,
        require_approval=False,
        urgent_remind_sent=False,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    return course.course_id


async def _chapter(db, course_id: int, name: str = "第一章") -> int:
    now = utcnow()
    ch = EtChapter(
        course_id=course_id,
        chapter_name=name,
        sort_order=1,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(ch)
    await db.flush()
    return ch.chapter_id


async def _item(db, chapter_id: int, *, title: str, order: int, quiz_id: int | None = None) -> int:
    """建一個章節項目。

    ⚠️ `ET_ITEM` **沒有 `TITLE` 欄位**，標題在 `ET_MATERIAL` / `ET_QUIZ` 上；且有
    CHECK constraint 強制 `MATERIAL`→`MATERIAL_ID` 必填、`QUIZ`→`QUIZ_ID` 必填且互斥。
    故教材項目要連帶建一筆 `ET_MATERIAL`。
    """
    now = utcnow()
    material_id = None
    if quiz_id is None:
        material = EtMaterial(
            material_name=title,
            version=0,
            created_user="admin01",
            created_date=now,
            deleted=0,
        )
        db.add(material)
        await db.flush()
        material_id = material.material_id
    item = EtItem(
        chapter_id=chapter_id,
        item_type=ITEM_QUIZ if quiz_id else ITEM_MATERIAL,
        sort_order=order,
        material_id=material_id,
        quiz_id=quiz_id,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(item)
    await db.flush()
    return item.item_id


async def _quiz(db, *, name: str = "小考", max_retry: int = 3, pass_score: int = 80) -> int:
    now = utcnow()
    quiz = EtQuiz(
        quiz_name=name,
        pass_score=pass_score,
        max_retry=max_retry,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(quiz)
    await db.flush()
    return quiz.quiz_id


async def _enroll(db, user_id: str, course_id: int, *, removed: bool = False, status: str = COMPLETION_NOT_STARTED):
    now = utcnow()
    row = EtEnrollment(
        user_id=user_id,
        course_id=course_id,
        join_source=SOURCE_INVITATION_CODE,
        joined_at=now,
        completion_status=status,
        is_removed=removed,
        created_user=user_id,
        created_date=now,
        deleted=0,
    )
    db.add(row)
    await db.flush()
    return row


async def _complete_item(db, user_id: str, course_id: int, item_id: int) -> None:
    now = utcnow()
    db.add(
        EtProgress(
            user_id=user_id,
            course_id=course_id,
            item_id=item_id,
            is_completed=True,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _attempt(db, *, user_id: str, course_id: int, quiz_id: int, no: int, score: Decimal, is_pass: bool) -> int:
    now = utcnow()
    row = EtQuizAttemptM(
        user_id=user_id,
        course_id=course_id,
        quiz_id=quiz_id,
        attempt_no=no,
        started_at=now - timedelta(minutes=10),
        submitted_at=now,
        status=ATTEMPT_SUBMITTED,
        score=score,
        is_pass=is_pass,
        pass_score_snapshot=80,
        time_limit_snapshot=None,
        question_order="[]",
        option_order="{}",
        created_user=user_id,
        created_date=now,
        deleted=0,
    )
    db.add(row)
    await db.flush()
    return row.attempt_id


async def _survey(db, course_id: int, *, name: str = "課後問卷") -> int:
    now = utcnow()
    survey = EtSurvey(
        course_id=course_id,
        survey_name=name,
        is_active=True,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(survey)
    await db.flush()
    return survey.survey_id


async def _sq(db, survey_id: int, *, stem: str, order: int, is_text: bool = False) -> int:
    now = utcnow()
    q = EtSurveyQuestion(
        survey_id=survey_id,
        question_type=SURVEY_QUESTION_TEXT if is_text else SURVEY_QUESTION_SINGLE,
        stem=stem,
        sort_order=order,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(q)
    await db.flush()
    return q.sq_id


async def _so(db, sq_id: int, *, text: str, order: int) -> int:
    now = utcnow()
    o = EtSurveyOption(
        sq_id=sq_id, option_text=text, sort_order=order, created_user="admin01", created_date=now, deleted=0
    )
    db.add(o)
    await db.flush()
    return o.so_id


async def _respond(db, survey_id: int, user_id: str, answers: list[tuple[int, int | None, str | None]]) -> None:
    """一位學員的一次填答。`answers` 為 `(sq_id, so_id, answer_text)`。"""
    now = utcnow()
    m = EtSurveyResponseM(
        survey_id=survey_id, user_id=user_id, submitted_at=now, created_user=user_id, created_date=now, deleted=0
    )
    db.add(m)
    await db.flush()
    for sq_id, so_id, text in answers:
        db.add(
            EtSurveyResponseD(
                response_id=m.response_id,
                sq_id=sq_id,
                so_id=so_id,
                answer_text=text,
                created_user=user_id,
                created_date=now,
                deleted=0,
            )
        )
    await db.flush()


async def _close_course(db, course_id: int, source: str) -> None:
    """讓課程「視同關閉」——兩種來源行為必須相同。

    `status` 走 `STATUS = CLOSED`；`expired` 把 `OPEN_END_AT` 改到過去。後者在本系統是
    **常態而非過渡狀態**——到期自動轉 `CLOSED` 屬 `ET-16`（未實作），故期間過了而
    `STATUS` 仍是 `PUBLISHED` 的課程一直存在。只判 `STATUS` 的實作會讓 `expired`
    那一半變紅。
    """
    now = utcnow()
    values = (
        {"status": COURSE_CLOSED, "closed_at": now}
        if source == "status"
        else {"open_start_at": now - timedelta(days=30), "open_end_at": now - timedelta(days=1)}
    )
    await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(**values))
    await db.flush()
    # 服務層是另一次查詢，但同一個 session 的 identity map 可能還握著舊的課程列
    db.expire_all()


_URL = "/api/et/courses"


class TestStudentList:
    """區塊 1：已加入學員清單（AC 1 / 2 / 3 / 5）。"""

    async def test_列出該課程之已加入學員(self, client, db) -> None:
        teacher = await _user(db, "t_tr01")
        course_id = await _course(db, owner=teacher)
        s1 = await _user(db, "s_tr01a", roles=(ROLE_STUDENT,), name="王小明")
        await _enroll(db, s1, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert [row["user_name"] for row in rows] == ["王小明"]

    async def test_已移除學員不列入但歷史保留(self, client, db) -> None:
        """AC 5：`IS_REMOVED` 者不出現於清單，**但 DB 的列與其學習歷史仍在**。"""
        teacher = await _user(db, "t_tr02")
        course_id = await _course(db, owner=teacher)
        kept = await _user(db, "s_tr02a", roles=(ROLE_STUDENT,), name="留下的")
        gone = await _user(db, "s_tr02b", roles=(ROLE_STUDENT,), name="被移除的")
        await _enroll(db, kept, course_id)
        removed_row = await _enroll(db, gone, course_id, removed=True)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert [row["user_name"] for row in r.json()["data"]] == ["留下的"]
        assert removed_row.enrollment_id is not None, "移除是軟刪，DB 的列必須還在"

    async def test_完課狀態不讀死欄位而是即時計算(self, client, db) -> None:
        """🔴 `ET_ENROLLMENT.COMPLETION_STATUS` **只在加入時寫入 `NOT_STARTED`**，
        沒有任何路徑推進它（ET04 於 #284 已踩過並註明「不讀它」）。

        本測試刻意把該欄位留在 `NOT_STARTED`，但讓學員實際完成所有項目——讀死欄位的
        實作會回 `NOT_STARTED`，即時計算才會回 `COMPLETED`。
        """
        teacher = await _user(db, "t_tr03")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        item_a = await _item(db, chapter_id, title="教材 A", order=1)
        item_b = await _item(db, chapter_id, title="教材 B", order=2)
        student = await _user(db, "s_tr03", roles=(ROLE_STUDENT,), name="全完成的")
        await _enroll(db, student, course_id, status=COMPLETION_NOT_STARTED)
        await _complete_item(db, student, course_id, item_a)
        await _complete_item(db, student, course_id, item_b)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        row = r.json()["data"][0]
        assert row["completion_status"] == COMPLETION_COMPLETED, "讀了死欄位就會回 NOT_STARTED"
        assert row["progress_pct"] == 100

    async def test_完課狀態三態與進度(self, client, db) -> None:
        teacher = await _user(db, "t_tr04")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        item_a = await _item(db, chapter_id, title="教材 A", order=1)
        await _item(db, chapter_id, title="教材 B", order=2)
        none_yet = await _user(db, "s_tr04a", roles=(ROLE_STUDENT,), name="未開始")
        halfway = await _user(db, "s_tr04b", roles=(ROLE_STUDENT,), name="進行中")
        await _enroll(db, none_yet, course_id)
        await _enroll(db, halfway, course_id)
        await _complete_item(db, halfway, course_id, item_a)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        by_name = {row["user_name"]: row for row in r.json()["data"]}
        assert by_name["未開始"]["completion_status"] == COMPLETION_NOT_STARTED
        assert by_name["未開始"]["progress_pct"] == 0
        assert by_name["進行中"]["completion_status"] == COMPLETION_IN_PROGRESS
        assert by_name["進行中"]["progress_pct"] == 50

    async def test_已刪除項目不灌大進度(self, client, db) -> None:
        """🔴 `ET_PROGRESS` 的列在項目被刪除後**仍然保留**（那是學習歷史，刻意不連帶刪）。

        分母會隨刪除縮小，分子若不一起濾就會超過 100%——教師刪掉一個項目，學員的進度
        就變成 150%。既有 `completion_counts_by_course` 的 docstring 已明載此陷阱。
        """
        teacher = await _user(db, "t_tr05")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        kept = await _item(db, chapter_id, title="留著的", order=1)
        doomed = await _item(db, chapter_id, title="要被刪的", order=2)
        student = await _user(db, "s_tr05", roles=(ROLE_STUDENT,), name="兩項都完成")
        await _enroll(db, student, course_id)
        await _complete_item(db, student, course_id, kept)
        await _complete_item(db, student, course_id, doomed)
        # 教師刪掉其中一個項目——progress 列刻意留著
        item = await db.get(EtItem, doomed)
        item.deleted = 1
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        row = r.json()["data"][0]
        assert row["progress_pct"] == 100, "分子未濾軟刪會得到 200%"
        assert row["completion_status"] == COMPLETION_COMPLETED


class TestAverageScore:
    """區塊 1 的平均成績（AC 3 / FR-ET-US9-03）。"""

    async def test_平均成績取各測驗最高分且排除未作答(self, client, db) -> None:
        """分母是**該學員有作答過的測驗數**，不是課程的測驗總數。

        課程有兩個測驗、學員只作答其中一個時，兩種分母會給出差一倍的數字。
        """
        teacher = await _user(db, "t_tr06")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_a = await _quiz(db, name="小考 A")
        quiz_b = await _quiz(db, name="小考 B")
        await _item(db, chapter_id, title="小考 A", order=1, quiz_id=quiz_a)
        await _item(db, chapter_id, title="小考 B", order=2, quiz_id=quiz_b)
        student = await _user(db, "s_tr06", roles=(ROLE_STUDENT,), name="只考了一科")
        await _enroll(db, student, course_id)
        # 同一測驗考兩次，取最高分 90（不是平均 75）
        await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=quiz_a, no=1, score=Decimal("60"), is_pass=False
        )
        await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=quiz_a, no=2, score=Decimal("90"), is_pass=True
        )
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        row = r.json()["data"][0]
        assert row["avg_score"] == "90.00", "應為已作答測驗的最高分平均（90），非含未作答的 45"

    async def test_完全未作答者平均成績為空(self, client, db) -> None:
        """AC 3：顯示「—」而非 0——0 分與未作答意義相反。"""
        teacher = await _user(db, "t_tr07")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr07", roles=(ROLE_STUDENT,), name="沒考過")
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"][0]["avg_score"] is None


class TestStudentListAuthorization:
    """授權：僅課程擁有者與管理者可看（FR-ET-US9-08 的前提）。"""

    async def test_他人課程之學員清單回四零三(self, client, db) -> None:
        owner = await _user(db, "t_tr08")
        other = await _user(db, "t_tr09")
        course_id = await _course(db, owner=owner)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(other))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_學員角色呼叫回四零三(self, client, db) -> None:
        teacher = await _user(db, "t_tr10")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr10", roles=(ROLE_STUDENT,))
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(student))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"


class TestAttemptOverview:
    """區塊 2：作答明細總覽（AC 4 / 6 / FR-ET-US9-04）。"""

    async def test_一次列出所有曾作答學員(self, client, db) -> None:
        """FR-ET-US9-04 明訂「**一次列出所有曾作答之學員**（不設學員篩選）」。"""
        teacher = await _user(db, "t_tr11")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, name="小考")
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        answered = await _user(db, "s_tr11a", roles=(ROLE_STUDENT,), name="有作答")
        silent = await _user(db, "s_tr11b", roles=(ROLE_STUDENT,), name="沒作答")
        await _enroll(db, answered, course_id)
        await _enroll(db, silent, course_id)
        await _attempt(
            db, user_id=answered, course_id=course_id, quiz_id=quiz_id, no=1, score=Decimal("70"), is_pass=False
        )
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        names = [s["user_name"] for s in r.json()["students"]]
        assert names == ["有作答"], "未作答者不進區塊 2（他在區塊 1 仍看得到）"

    async def test_展開見歷次attempt清單(self, client, db) -> None:
        """AC 4：每列顯示作答時間、總分、是否及格；重考多次者**每次都在**。"""
        teacher = await _user(db, "t_tr12")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, name="小考")
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr12", roles=(ROLE_STUDENT,), name="考三次")
        await _enroll(db, student, course_id)
        for no, score in ((1, "50"), (2, "70"), (3, "90")):
            await _attempt(
                db,
                user_id=student,
                course_id=course_id,
                quiz_id=quiz_id,
                no=no,
                score=Decimal(score),
                is_pass=(score == "90"),
            )
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(teacher))

        quizzes = r.json()["students"][0]["quizzes"]
        assert len(quizzes) == 1
        attempts = quizzes[0]["attempts"]
        assert [a["attempt_no"] for a in attempts] == [1, 2, 3], "不限最近一次，且依次別遞增"
        assert [a["score"] for a in attempts] == ["50.00", "70.00", "90.00"]
        assert attempts[2]["is_pass"] is True

    async def test_未作答之測驗標示尚未作答(self, client, db) -> None:
        """AC 8 / ET-MSG-ET03-005：該學員對某測驗無 attempt 時仍要列出那個測驗。

        整個測驗不出現的話，教師分不出「他沒考」與「這門課沒這個測驗」。
        """
        teacher = await _user(db, "t_tr13")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        done_quiz = await _quiz(db, name="考過的")
        skipped_quiz = await _quiz(db, name="沒考的")
        await _item(db, chapter_id, title="考過的", order=1, quiz_id=done_quiz)
        await _item(db, chapter_id, title="沒考的", order=2, quiz_id=skipped_quiz)
        student = await _user(db, "s_tr13", roles=(ROLE_STUDENT,), name="只考一科")
        await _enroll(db, student, course_id)
        await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=done_quiz, no=1, score=Decimal("80"), is_pass=True
        )
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(teacher))

        by_quiz = {q["quiz_name"]: q for q in r.json()["students"][0]["quizzes"]}
        assert by_quiz["沒考的"]["attempts"] == []
        assert len(by_quiz["考過的"]["attempts"]) == 1


class TestAttemptDetailForTeacher:
    """區塊 2：教師端單次逐題明細（AC 4 / FR-ET-US9-05）。"""

    async def test_教師可看自己課程學員的逐題明細(self, client, db) -> None:
        teacher = await _user(db, "t_tr14")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr14", roles=(ROLE_STUDENT,), name="學員")
        await _enroll(db, student, course_id)
        attempt_id = await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=quiz_id, no=1, score=Decimal("75"), is_pass=False
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt_id}/detail", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.json()["attempt_id"] == attempt_id
        assert r.json()["user_name"] == "學員", "教師端要知道這是誰的考卷"

    async def test_他人課程之attempt明細回四零三(self, client, db) -> None:
        """🔴 授權以「該 attempt 的**課程擁有者**」判定，不是學員端的 `USER_ID` 比對。

        學員端 `_require_own_attempt` 只能看自己的；教師端要能看別人的，但**只限自己
        課程裡的**。放寬成「任何教師都能看」等於全站考卷對所有教師公開。
        """
        owner = await _user(db, "t_tr15")
        outsider = await _user(db, "t_tr16")
        course_id = await _course(db, owner=owner)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr15", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        attempt_id = await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=quiz_id, no=1, score=Decimal("60"), is_pass=False
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt_id}/detail", headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_學員角色不可用教師端明細端點(self, client, db) -> None:
        """學員要看自己的明細有學員端端點；本支是教師端，角色閘擋下。"""
        teacher = await _user(db, "t_tr17")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr17", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        attempt_id = await _attempt(
            db, user_id=student, course_id=course_id, quiz_id=quiz_id, no=1, score=Decimal("60"), is_pass=False
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt_id}/detail", headers=_bearer(student))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"


class TestResetRetry:
    """重置重考次數（AC 6 / FR-ET-US9-06）。"""

    def _url(self, course_id: int, user_id: str, quiz_id: int) -> str:
        return f"{_URL}/{course_id}/students/{user_id}/quizzes/{quiz_id}/retry-reset"

    async def test_次數用盡且未及格可重置且不刪紀錄(self, client, db) -> None:
        """🔴 AC 6 明訂「重置後**歷次 attempt 明細仍完整可回看**」。

        刪除 attempt 會同時毀掉學員的歷史與教師的追蹤資料——而那個損失沒有任何地方
        救得回來。本測試在重置後直接數 DB 的列。
        """
        teacher = await _user(db, "t_tr18")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=1)  # 總配額 2 次
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr18", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        for no in (1, 2):
            await _attempt(
                db,
                user_id=student,
                course_id=course_id,
                quiz_id=quiz_id,
                no=no,
                score=Decimal("50"),
                is_pass=False,
            )
        await db.commit()

        r = await client.post(self._url(course_id, student, quiz_id), headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        kept = await db.scalar(
            select(func.count(EtQuizAttemptM.attempt_id)).where(
                EtQuizAttemptM.user_id == student, EtQuizAttemptM.quiz_id == quiz_id
            )
        )
        assert kept == 2, "重置 MUST NOT 刪除任何 attempt"
        base = await db.scalar(
            select(func.max(EtQuizRetryReset.attempt_count_at_reset)).where(
                EtQuizRetryReset.user_id == student, EtQuizRetryReset.quiz_id == quiz_id
            )
        )
        assert base == 2, "基準應為重置當下的 attempt 總數"

    async def test_重置後該學員可再作答(self, client, db) -> None:
        """重置的意義就在這裡——`used` 歸零、`can_reset` 轉回 false。"""
        teacher = await _user(db, "t_tr19")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=1)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr19", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        for no in (1, 2):
            await _attempt(
                db,
                user_id=student,
                course_id=course_id,
                quiz_id=quiz_id,
                no=no,
                score=Decimal("50"),
                is_pass=False,
            )
        await db.commit()
        await client.post(self._url(course_id, student, quiz_id), headers=_bearer(teacher))

        r = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(teacher))

        quiz_row = r.json()["students"][0]["quizzes"][0]
        assert quiz_row["used_attempts"] == 0, "本輪已用次數應歸零"
        assert quiz_row["can_reset"] is False, "配額已滿，不該再顯示可重置"
        assert len(quiz_row["attempts"]) == 2, "歷次明細仍完整可回看"

    async def test_次數未用盡不可重置(self, client, db) -> None:
        """AC 6 的負向：還剩最後一次時按下去會白送一輪配額。"""
        teacher = await _user(db, "t_tr20")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=3)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr20", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _attempt(
            db,
            user_id=student,
            course_id=course_id,
            quiz_id=quiz_id,
            no=1,
            score=Decimal("50"),
            is_pass=False,
        )
        await db.commit()

        r = await client.post(self._url(course_id, student, quiz_id), headers=_bearer(teacher))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_002"

    async def test_已及格不可重置(self, client, db) -> None:
        teacher = await _user(db, "t_tr21")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=0)  # 總配額 1 次
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr21", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _attempt(
            db,
            user_id=student,
            course_id=course_id,
            quiz_id=quiz_id,
            no=1,
            score=Decimal("95"),
            is_pass=True,
        )
        await db.commit()

        r = await client.post(self._url(course_id, student, quiz_id), headers=_bearer(teacher))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_002"


class TestRemoveStudent:
    """移除學員（AC 7 / 8 / FR-ET-US9-10）。"""

    async def test_移除寫入標記且歷史保留(self, client, db) -> None:
        teacher = await _user(db, "t_tr22")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        item_id = await _item(db, chapter_id, title="教材", order=1)
        student = await _user(db, "s_tr22", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _complete_item(db, student, course_id, item_id)
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(teacher))

        assert r.status_code == 204, r.text
        db.expire_all()
        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == course_id)
        )
        assert row.is_removed is True
        assert row.removed_at is not None, "REMOVED_AT 為稽核依據，必須寫入"
        kept = await db.scalar(select(func.count(EtProgress.progress_id)).where(EtProgress.user_id == student))
        assert kept == 1, "學習歷史 MUST 完整保留供稽核"

    async def test_移除後不再出現於清單(self, client, db) -> None:
        teacher = await _user(db, "t_tr23")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr23", roles=(ROLE_STUDENT,), name="要被移除的")
        await _enroll(db, student, course_id)
        await db.commit()
        await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(teacher))

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"] == []

    async def test_移除作答中學員其attempt仍保留(self, client, db) -> None:
        """AC 7：有 `IN_PROGRESS` attempt 時仍允許移除，**該 attempt 保留並計入歷史**。

        警告文案（ET-MSG-ET03-003）由前端顯示；後端不擋——擋下來會讓教師沒辦法移除一個
        正在作答的人，而那正是最需要移除的情境。
        """
        teacher = await _user(db, "t_tr24")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr24", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        now = utcnow()
        db.add(
            EtQuizAttemptM(
                user_id=student,
                course_id=course_id,
                quiz_id=quiz_id,
                attempt_no=1,
                started_at=now,
                submitted_at=None,
                status=ATTEMPT_IN_PROGRESS,
                score=None,
                is_pass=None,
                pass_score_snapshot=80,
                time_limit_snapshot=None,
                question_order="[]",
                option_order="{}",
                created_user=student,
                created_date=now,
                deleted=0,
            )
        )
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(teacher))

        assert r.status_code == 204, r.text
        kept = await db.scalar(select(func.count(EtQuizAttemptM.attempt_id)).where(EtQuizAttemptM.user_id == student))
        assert kept == 1, "作答中的 attempt 必須保留並計入歷史"

    async def test_移除已移除者回四零四(self, client, db) -> None:
        """重複移除不是「無害的冪等」——它代表教師看到的清單已過期。"""
        teacher = await _user(db, "t_tr25")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr25", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id, removed=True)
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(teacher))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_TRACK_001"


@pytest.mark.parametrize("source", ["status", "expired"])
class TestClosedCourseIsReadOnly:
    """AC 10 / FR-ET-US9-11：課程已關閉時可讀不可寫。

    **兩種來源都驗**——「已發布但期間已過」在本系統是常態（ET-16 未實作），只判
    `STATUS` 的實作會讓 `expired` 那一半變紅。
    """

    async def test_已關閉時不可重置(self, client, db, source: str) -> None:
        teacher = await _user(db, f"t_tr26{source[:3]}")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=0)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, f"s_tr26{source[:3]}", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _attempt(
            db,
            user_id=student,
            course_id=course_id,
            quiz_id=quiz_id,
            no=1,
            score=Decimal("50"),
            is_pass=False,
        )
        await _close_course(db, course_id, source)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/students/{student}/quizzes/{quiz_id}/retry-reset", headers=_bearer(teacher)
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_003"

    async def test_已關閉時不可移除(self, client, db, source: str) -> None:
        teacher = await _user(db, f"t_tr27{source[:3]}")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, f"s_tr27{source[:3]}", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _close_course(db, course_id, source)
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(teacher))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_003"

    async def test_已關閉仍可閱覽(self, client, db, source: str) -> None:
        """AC 10 的另一半：關閉只停**寫入**，閱覽照常（#255 裁示 Q2=A「讀照舊、寫全停」）。

        只驗擋得住而不驗讀得到的話，把整頁改成 409 也會全綠。
        """
        teacher = await _user(db, f"t_tr28{source[:3]}")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, f"s_tr28{source[:3]}", roles=(ROLE_STUDENT,), name="仍看得到")
        await _enroll(db, student, course_id)
        await _close_course(db, course_id, source)
        await db.commit()

        listed = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))
        overview = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(teacher))

        assert listed.status_code == 200, listed.text
        assert [row["user_name"] for row in listed.json()["data"]] == ["仍看得到"]
        assert overview.status_code == 200, overview.text


class TestSurveyResult:
    """區塊 3：問卷結果（AC 9 / 10 / 11 / FR-ET-US9-07）。"""

    async def test_課程無問卷時回空(self, client, db) -> None:
        """AC 11 / FR-ET-US9-07：課程無問卷時**本區塊隱藏**。

        回 `has_survey=false` 讓前端決定不渲染整個區塊——回 404 會讓前端分不出
        「這門課沒問卷」與「你沒權限 / 課程不存在」。
        """
        teacher = await _user(db, "t_tr30")
        course_id = await _course(db, owner=teacher)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.json()["has_survey"] is False

    async def test_單選題統計選項分布(self, client, db) -> None:
        """AC 9：單選題呈現各選項人數。百分比由前端算（後端只回原始人數）。"""
        teacher = await _user(db, "t_tr31")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        sq = await _sq(db, survey_id, stem="滿意嗎？", order=1)
        good = await _so(db, sq, text="滿意", order=1)
        soso = await _so(db, sq, text="普通", order=2)
        for idx, so_id in enumerate((good, good, soso)):
            student = await _user(db, f"s_tr31{idx}", roles=(ROLE_STUDENT,))
            await _enroll(db, student, course_id)
            await _respond(db, survey_id, student, [(sq, so_id, None)])
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        body = r.json()
        assert body["has_survey"] is True
        counts = {o["option_text"]: o["count"] for o in body["questions"][0]["options"]}
        assert counts == {"滿意": 2, "普通": 1}

    async def test_問答題統計只回已答人數不回文字(self, client, db) -> None:
        """🔴 FR-ET-US9-07（2026-08-28 裁示）：**統計檢視**之問答題僅呈現已答人數。

        長短不一的文字會把單選題的分布擠到看不見；問答題的價值在逐則閱讀，本就屬明細。
        故統計區段**不可**帶出 `answer_text`——那會讓裁示失效，而畫面上只是「變得很長」。
        """
        teacher = await _user(db, "t_tr32")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        sq = await _sq(db, survey_id, stem="建議？", order=1, is_text=True)
        student = await _user(db, "s_tr32", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await _respond(db, survey_id, student, [(sq, None, "希望多一點實作")])
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        question = r.json()["questions"][0]
        assert question["answered_count"] == 1
        assert question["options"] == [], "問答題沒有選項分布"
        assert "希望多一點實作" not in r.text.split('"details"')[0], "統計區段不可帶出文字答案"

    async def test_明細逐學員具名且含問答文字(self, client, db) -> None:
        """AC 10 / FR-ET-US9-07：**明細檢視**逐學員具名，問答題顯示文字答案。"""
        teacher = await _user(db, "t_tr33")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        single = await _sq(db, survey_id, stem="滿意嗎？", order=1)
        good = await _so(db, single, text="滿意", order=1)
        text_q = await _sq(db, survey_id, stem="建議？", order=2, is_text=True)
        student = await _user(db, "s_tr33", roles=(ROLE_STUDENT,), name="陳同學")
        await _enroll(db, student, course_id)
        await _respond(db, survey_id, student, [(single, good, None), (text_q, None, "課程很紮實")])
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        detail = r.json()["details"][0]
        assert detail["user_name"] == "陳同學", "問卷填答為具名資料"
        answers = {a["sq_id"]: a for a in detail["answers"]}
        assert answers[single]["option_text"] == "滿意"
        assert answers[text_q]["answer_text"] == "課程很紮實"

    async def test_已填未填人數以在籍學員為母體(self, client, db) -> None:
        """AC 9：整份問卷之已填 / 未填人數。

        未填人數的母體是**在籍學員**（已移除者不計入，比照完課率分母的定義）。
        """
        teacher = await _user(db, "t_tr34")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        sq = await _sq(db, survey_id, stem="滿意嗎？", order=1)
        opt = await _so(db, sq, text="滿意", order=1)
        filled = await _user(db, "s_tr34a", roles=(ROLE_STUDENT,))
        blank = await _user(db, "s_tr34b", roles=(ROLE_STUDENT,))
        gone = await _user(db, "s_tr34c", roles=(ROLE_STUDENT,))
        await _enroll(db, filled, course_id)
        await _enroll(db, blank, course_id)
        await _enroll(db, gone, course_id, removed=True)
        await _respond(db, survey_id, filled, [(sq, opt, None)])
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        body = r.json()
        assert body["filled_count"] == 1
        assert body["not_filled_count"] == 1, "已移除的學員不計入母體"

    async def test_尚無填答時統計為零而非空區塊(self, client, db) -> None:
        """AC 12 / ET-MSG-ET03-006：各選項 0 人、已填 0 / 未填 N；明細為空清單。

        整個 `questions` 回空陣列會讓教師以為問卷沒有題目。
        """
        teacher = await _user(db, "t_tr35")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        sq = await _sq(db, survey_id, stem="滿意嗎？", order=1)
        await _so(db, sq, text="滿意", order=1)
        student = await _user(db, "s_tr35", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(teacher))

        body = r.json()
        assert body["has_survey"] is True
        assert len(body["questions"]) == 1, "題目仍要列出，只是統計為 0"
        assert body["questions"][0]["options"][0]["count"] == 0
        assert body["filled_count"] == 0
        assert body["not_filled_count"] == 1
        assert body["details"] == []

    async def test_他人課程之問卷結果回四零三(self, client, db) -> None:
        """🔴 FR-ET-US9-08：問卷填答為**具名**資料，僅本課程教師與管理者可見。

        這是本頁個資密度最高的一處——它把「誰說了什麼」直接對應到姓名。
        """
        owner = await _user(db, "t_tr36")
        outsider = await _user(db, "t_tr37")
        course_id = await _course(db, owner=owner)
        await _survey(db, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result", headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestCsvExport:
    """兩支 CSV 匯出（AC 9 / FR-ET-US9-09）。"""

    async def test_學員清單csv含完整欄位與BOM(self, client, db) -> None:
        """含 UTF-8 BOM——沒有它 Excel 開啟會把中文顯示成亂碼。"""
        teacher = await _user(db, "t_tr40")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        await _item(db, chapter_id, title="教材", order=1)
        student = await _user(db, "s_tr40", roles=(ROLE_STUDENT,), name="王小明")
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.content.startswith(b"\xef\xbb\xbf"), "缺 BOM 會讓 Excel 顯示亂碼"
        text = r.content.decode("utf-8-sig")
        assert "王小明" in text
        for header in ("學員", "加入日期", "完課狀態", "學習進度", "平均成績", "最後活動"):
            assert header in text, f"缺欄位：{header}"

    async def test_學員清單csv不受分頁限制(self, client, db) -> None:
        """匯出是**全量**——分頁是畫面的事，CSV 的用途正是帶走全部。"""
        teacher = await _user(db, "t_tr41")
        course_id = await _course(db, owner=teacher)
        for idx in range(25):
            student = await _user(db, f"s_tr41{idx:02d}", roles=(ROLE_STUDENT,), name=f"學員{idx:02d}")
            await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        text = r.content.decode("utf-8-sig")
        assert text.count("學員") >= 25, "每位學員一列（預設分頁 20 筆不該限制匯出）"

    async def test_csv防公式注入(self, client, db) -> None:
        """🔴 CWE-1236：試算表會把 `=` `+` `-` `@` 開頭的欄位當**公式執行**。

        本 CSV 含學員姓名與問答題自由文字，正是最典型的注入輸入。`sanitize_csv_cell`
        前置單引號中和，令試算表視為文字。
        """
        teacher = await _user(db, "t_tr42")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr42", roles=(ROLE_STUDENT,), name="=1+1")
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        text = r.content.decode("utf-8-sig")
        assert "'=1+1" in text, "危險前導字元必須被中和"

    async def test_問卷結果csv含問答題文字(self, client, db) -> None:
        """FR-ET-US9-09 明訂問卷 CSV **MUST 含問答題之文字答案**。

        統計檢視刻意不顯示那些文字（會擠掉單選分布），但 CSV 的用途本就是帶走細節——
        兩者不衝突，且少了文字的匯出等於讓教師拿不到問卷最有價值的部分。
        """
        teacher = await _user(db, "t_tr43")
        course_id = await _course(db, owner=teacher)
        survey_id = await _survey(db, course_id)
        single = await _sq(db, survey_id, stem="滿意嗎？", order=1)
        good = await _so(db, single, text="滿意", order=1)
        text_q = await _sq(db, survey_id, stem="建議？", order=2, is_text=True)
        student = await _user(db, "s_tr43", roles=(ROLE_STUDENT,), name="陳同學")
        await _enroll(db, student, course_id)
        await _respond(db, survey_id, student, [(single, good, None), (text_q, None, "希望多一點實作")])
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result.csv", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        text = r.content.decode("utf-8-sig")
        assert "陳同學" in text, "問卷填答為具名資料"
        assert "希望多一點實作" in text, "MUST 含問答題文字答案"
        assert "滿意" in text

    async def test_課程無問卷時匯出回四零四(self, client, db) -> None:
        """畫面上本區塊是隱藏的，會打到這支就代表前端狀態已過期。

        回一個只有表頭的空 CSV 會讓教師以為「問卷沒有人填」，而實際上是沒有問卷。
        """
        teacher = await _user(db, "t_tr44")
        course_id = await _course(db, owner=teacher)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result.csv", headers=_bearer(teacher))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_TRACK_005"

    async def test_他人課程之csv回四零三(self, client, db) -> None:
        """匯出與畫面同一道授權——CSV 是最容易被當成「只是下載」而漏掉把關的入口。"""
        owner = await _user(db, "t_tr45")
        outsider = await _user(db, "t_tr46")
        course_id = await _course(db, owner=owner)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_已關閉課程仍可匯出(self, client, db) -> None:
        """AC 10 明訂關閉後「仍可閱覽三區塊全部內容（**含匯出 CSV**）」。

        匯出是讀，不是寫——套上寫入閘會讓教師在課程結束後拿不走自己的教學紀錄。
        """
        teacher = await _user(db, "t_tr47")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr47", roles=(ROLE_STUDENT,), name="結訓學員")
        await _enroll(db, student, course_id)
        await _close_course(db, course_id, "expired")
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert "結訓學員" in r.content.decode("utf-8-sig")


class TestWriteEndpointAuthorization:
    """兩支**寫入**端點與 `attempt-overview` 的授權（Security Review M-2 補）。

    原本只測了四支唯讀端點的「他人課程 403」，獨獨漏掉寫入端點——而那兩支的後果比
    唯讀嚴重得多（改別人學員的配額、把別人的學員移除）。
    """

    async def test_他人課程之重置回四零三(self, client, db) -> None:
        owner = await _user(db, "t_tr50")
        outsider = await _user(db, "t_tr51")
        course_id = await _course(db, owner=owner)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=0)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr50", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/students/{student}/quizzes/{quiz_id}/retry-reset", headers=_bearer(outsider)
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_他人課程之移除回四零三(self, client, db) -> None:
        owner = await _user(db, "t_tr52")
        outsider = await _user(db, "t_tr53")
        course_id = await _course(db, owner=owner)
        student = await _user(db, "s_tr52", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_他人課程之作答總覽回四零三(self, client, db) -> None:
        owner = await _user(db, "t_tr54")
        outsider = await _user(db, "t_tr55")
        course_id = await _course(db, owner=owner)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/attempt-overview", headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_學員角色不可重置(self, client, db) -> None:
        teacher = await _user(db, "t_tr56")
        course_id = await _course(db, owner=teacher)
        chapter_id = await _chapter(db, course_id)
        quiz_id = await _quiz(db, max_retry=0)
        await _item(db, chapter_id, title="小考", order=1, quiz_id=quiz_id)
        student = await _user(db, "s_tr56", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/students/{student}/quizzes/{quiz_id}/retry-reset", headers=_bearer(student)
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"

    async def test_學員角色不可移除(self, client, db) -> None:
        teacher = await _user(db, "t_tr57")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr57", roles=(ROLE_STUDENT,))
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(student))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"

    async def test_不可拿別的課程的測驗來重置(self, client, db) -> None:
        """🔴 這是整份 PR 裡**唯一一道 `ensure_owner` 看不到的防線**。

        教師拿自己課程的 `course_id` 配上別人課程的 `quiz_id`：`ensure_owner` 只檢查
        課程，完全不會察覺 `quiz_id` 來自別處。擋下來的是 `get_quiz_in_course`。

        沒有這條測試釘住的話，日後有人為了省一次查詢把它拿掉，CI 會全綠。
        """
        mine = await _user(db, "t_tr58")
        theirs = await _user(db, "t_tr59")
        my_course = await _course(db, owner=mine, name="我的課")
        their_course = await _course(db, owner=theirs, name="他的課")
        their_chapter = await _chapter(db, their_course)
        their_quiz = await _quiz(db, name="他的小考", max_retry=0)
        await _item(db, their_chapter, title="他的小考", order=1, quiz_id=their_quiz)
        student = await _user(db, "s_tr58", roles=(ROLE_STUDENT,))
        await _enroll(db, student, my_course)
        await _enroll(db, student, their_course)
        await _attempt(
            db,
            user_id=student,
            course_id=their_course,
            quiz_id=their_quiz,
            no=1,
            score=Decimal("50"),
            is_pass=False,
        )
        await db.commit()

        r = await client.post(
            f"{_URL}/{my_course}/students/{student}/quizzes/{their_quiz}/retry-reset", headers=_bearer(mine)
        )

        assert r.status_code == 404, "測驗不屬於該課程，不可跨課程重置"
        assert r.json()["error_code"] == "ET_TRACK_004"


class TestExportAudit:
    """具名個資匯出留痕（SA 裁示 2026-09-14 / Security Review M-3）。"""

    async def test_匯出學員清單寫稽核(self, client, db) -> None:
        teacher = await _user(db, "t_tr60")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr60", roles=(ROLE_STUDENT,), name="王小明")
        await _enroll(db, student, course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        logged = await db.scalar(
            select(func.count(DpAuditLog.log_id)).where(
                DpAuditLog.func_name == "ET-EXPORT",
                DpAuditLog.created_user == teacher,
                DpAuditLog.target_id == str(course_id),
            )
        )
        assert logged == 1, "匯出是把全班具名資料帶離系統，必須留痕"

    async def test_稽核不寫入姓名或答案內容(self, client, db) -> None:
        """稽核記「誰在何時帶走了多少」，不記內容。

        把姓名或問答文字寫進 `DP_AUDIT_LOG` 等於把個資複製到第二個地方——稽核表的保存
        期限與存取控制都與業務表不同。
        """
        teacher = await _user(db, "t_tr61")
        course_id = await _course(db, owner=teacher)
        student = await _user(db, "s_tr61", roles=(ROLE_STUDENT,), name="極機密姓名")
        await _enroll(db, student, course_id)
        await db.commit()
        await client.get(f"{_URL}/{course_id}/students.csv", headers=_bearer(teacher))

        description = await db.scalar(
            select(DpAuditLog.description).where(
                DpAuditLog.func_name == "ET-EXPORT", DpAuditLog.created_user == teacher
            )
        )
        assert "極機密姓名" not in (description or "")
        assert "1 筆" in (description or ""), "應記筆數"

    async def test_無問卷時不留無意義的匯出紀錄(self, client, db) -> None:
        """404 的請求沒有帶走任何東西，不該產生稽核列。"""
        teacher = await _user(db, "t_tr62")
        course_id = await _course(db, owner=teacher)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/survey-result.csv", headers=_bearer(teacher))

        assert r.status_code == 404
        logged = await db.scalar(
            select(func.count(DpAuditLog.log_id)).where(
                DpAuditLog.func_name == "ET-EXPORT", DpAuditLog.created_user == teacher
            )
        )
        assert logged == 0
