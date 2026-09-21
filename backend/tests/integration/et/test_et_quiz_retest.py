"""測驗變更後要求已通過學員重測（US3 / US6 / #361）。

此處只驗**需要真 DB 才驗得了**的事：批次同時寫多張表（重置基準、進度）、
「不刪 attempt」這條只有真資料才驗得到的保證、以及未通過者不受影響。

## 為什麼這條路徑不能重用 `reset_retry`

`tracking/rules.can_reset_retry` 在 `is_passed=True` 時回 `False`（理由：「他已經通過了；
再考只有機會把成績弄低」）——而本功能的對象**正是已通過的學員**，兩者前提相反。
⛔ 不可為了重用而放寬那個守門，它保護的是教師手動重置（US9 AC 6）。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.constants import (
    ATTEMPT_SUBMITTED,
    COMPLETION_NOT_STARTED,
    COURSE_PUBLISHED,
    ITEM_QUIZ,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuiz, EtQuizAttemptM, EtQuizRetryReset
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, roles: tuple[str, ...] = (ROLE_TEACHER,)) -> str:
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
    for role in roles:
        db.add(
            EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
        )
    await db.flush()
    return user_id


async def _course_with_quiz(db, owner: str) -> tuple[int, int, int]:
    """已發布且在開放期間內的課程 + 一個測驗項目。回 `(course_id, item_id, quiz_id)`。

    ⚠️ `open_start_at` 必須是過去——#379 起 `progress` / `attempt` 對「課程尚未開放」
    有守門，起始時間未到會讓學員端相關操作回 409。
    """
    now = utcnow()
    course = EtCourse(
        course_name="輸血作業標準流程教育訓練",
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

    chapter = EtChapter(
        course_id=course.course_id,
        chapter_name="第一章",
        sort_order=1,
        version=0,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(chapter)
    await db.flush()

    # ⚠️ `ET_QUIZ` 沒有 `COURSE_ID`——測驗與課程的關聯只經 `ET_ITEM.QUIZ_ID`。
    quiz = EtQuiz(
        quiz_name="輸血作業概念測驗",
        pass_score=80,
        max_retry=2,
        version=0,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(quiz)
    await db.flush()

    item = EtItem(
        chapter_id=chapter.chapter_id,
        item_type=ITEM_QUIZ,
        sort_order=1,
        material_id=None,
        quiz_id=quiz.quiz_id,
        version=0,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(item)
    await db.flush()
    return course.course_id, item.item_id, quiz.quiz_id


async def _enroll(db, user_id: str, course_id: int) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status=COMPLETION_NOT_STARTED,
            is_removed=False,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _attempt(db, *, user_id: str, course_id: int, quiz_id: int, no: int, score: int, is_pass: bool) -> None:
    now = utcnow()
    db.add(
        EtQuizAttemptM(
            user_id=user_id,
            course_id=course_id,
            quiz_id=quiz_id,
            attempt_no=no,
            started_at=now - timedelta(minutes=10),
            submitted_at=now,
            status=ATTEMPT_SUBMITTED,
            score=Decimal(score),
            is_pass=is_pass,
            pass_score_snapshot=80,
            time_limit_snapshot=None,
            question_order="[]",
            option_order="{}",
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


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


async def _passed_student(db, *, uid: str, course_id: int, item_id: int, quiz_id: int) -> str:
    """一位已通過的學員：在籍、有一次及格 attempt、該測驗項目已標完成。"""
    await _user(db, uid, roles=(ROLE_STUDENT,))
    await _enroll(db, uid, course_id)
    await _attempt(db, user_id=uid, course_id=course_id, quiz_id=quiz_id, no=1, score=90, is_pass=True)
    await _complete_item(db, uid, course_id, item_id)
    return uid


async def _settings_body(db, quiz_id: int, *, pass_score: int, require_retest: bool) -> dict:
    quiz = await db.get(EtQuiz, quiz_id)
    return {
        "quiz_name": quiz.quiz_name,
        "description": None,
        "pass_score": pass_score,
        "time_limit_min": None,
        "max_retry": quiz.max_retry,
        "version": quiz.version,
        "require_retest": require_retest,
    }


async def _facts(db, *, uid: str, quiz_id: int, item_id: int) -> tuple[int, int, bool]:
    """回 `(attempt 數, 重置基準列數, 該項目是否仍標完成)`。"""
    attempts = await db.scalar(
        select(func.count())
        .select_from(EtQuizAttemptM)
        .where(EtQuizAttemptM.user_id == uid, EtQuizAttemptM.quiz_id == quiz_id, EtQuizAttemptM.deleted == 0)
    )
    # `ET_QUIZ_RETRY_RESET` 是 append-only（無 `DELETED` 欄位）——重置基準只增不減。
    resets = await db.scalar(
        select(func.count())
        .select_from(EtQuizRetryReset)
        .where(EtQuizRetryReset.user_id == uid, EtQuizRetryReset.quiz_id == quiz_id)
    )
    done = await db.scalar(
        select(EtProgress.is_completed).where(
            EtProgress.user_id == uid, EtProgress.item_id == item_id, EtProgress.deleted == 0
        )
    )
    return attempts, resets, bool(done)


class TestPassedCount:
    """確認框要寫出受影響人數，否則教師無從判斷該選是或否。"""

    async def test_測驗詳細帶出已通過人數(self, client, db):
        teacher = await _user(db, "ZTT010")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS010", course_id=cid, item_id=item_id, quiz_id=qid)
        await _passed_student(db, uid="ZTS011", course_id=cid, item_id=item_id, quiz_id=qid)
        failed = await _user(db, "ZTS012", roles=(ROLE_STUDENT,))
        await _enroll(db, failed, cid)
        await _attempt(db, user_id=failed, course_id=cid, quiz_id=qid, no=1, score=30, is_pass=False)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["passed_count"] == 2, "只算曾及格者，未通過的不計入"

    async def test_非擁有者看不到人數(self, client, db):
        # 比照同一回應既有的答案遮蔽：非擁有者可讀題目，但看不到這門課的學員統計。
        owner = await _user(db, "ZTT013")
        other = await _user(db, "ZTT014")
        cid, item_id, qid = await _course_with_quiz(db, owner)
        await _passed_student(db, uid="ZTS013", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(other))
        assert r.status_code == 200, r.text
        assert r.json()["passed_count"] is None, "非擁有者應拿到 None 而非 0——0 是錯誤資訊"


class TestRequireRetestOnQuizChange:
    async def test_選是時已通過學員次數歸零且完成狀態清除(self, client, db):
        teacher = await _user(db, "ZTT001")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS001", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        _, resets, done = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert resets == 1, "應寫入一列 ET_QUIZ_RETRY_RESET 作為次數歸零的基準"
        assert done is False, "該測驗項目的 IS_COMPLETED 應被清除，完課狀態才會回退"

    async def test_不論如何都不刪除任何_attempt(self, client, db):
        # 🔴 US6 AC 12 / US9 AC 6 與 #279 裁示 Q2=C：重置一律以基準列記，**不刪 attempt**。
        # 刪掉會同時毀掉學員回看自己考卷的能力與教師的追蹤資料，且無處可救。
        teacher = await _user(db, "ZTT002")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS002", course_id=cid, item_id=item_id, quiz_id=qid)
        await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=2, score=95, is_pass=True)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        attempts, _, _ = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert attempts == 2, "兩次 attempt 都必須留著（軟刪除也不行）"

    async def test_選否時學員狀態完全不動(self, client, db):
        teacher = await _user(db, "ZTT003")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS003", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=False)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        facts = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert facts == (1, 0, True), "選否時不應寫入基準、不應清除完成狀態"

    async def test_受影響學員各收到一封通知信(self, client, db):
        # ⚠️ 必須篩 STATUS='PENDING'：params key 對不上時平台會寫一列 FAILED 的空信，
        # 不篩的話「有列」本身就成立，測試會假陽性通過而實際沒有人收到信。
        teacher = await _user(db, "ZTT005")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS005", course_id=cid, item_id=item_id, quiz_id=qid)
        await _passed_student(db, uid="ZTS006", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 2, "兩位受影響的學員應各排入一封；逐人一封而非合批（範本含 {USER_NAME}）"

    async def test_未通過的學員不受影響(self, client, db):
        # 未通過者本來就還要重考，寫基準等於白送一輪配額——而畫面上看不出哪裡不對。
        teacher = await _user(db, "ZTT004")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        failed = await _user(db, "ZTS004", roles=(ROLE_STUDENT,))
        await _enroll(db, failed, cid)
        await _attempt(db, user_id=failed, course_id=cid, quiz_id=qid, no=1, score=40, is_pass=False)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        attempts, resets, _ = await _facts(db, uid=failed, quiz_id=qid, item_id=item_id)
        assert (attempts, resets) == (1, 0), "未通過者不應被寫入重置基準"
