"""ET03 學員學習狀況追蹤整合測試（US9 / #322）。

此處只驗**需要真 DB 才驗得了**的事：跨表聚合（完課數 / 總項目數 / 最高分平均）、
軟刪除過濾、以及「死欄位不可讀」這類只有真資料才會暴露的問題。

純推導（`can_reset_retry`、完課三態）於 `tests/unit/et/test_tracking_rules.py`。
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    ATTEMPT_SUBMITTED,
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    COMPLETION_NOT_STARTED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuiz, EtQuizAttemptM
from app.et.roles.models import EtUserRole

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
