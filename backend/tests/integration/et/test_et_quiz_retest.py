"""測驗變更後要求學員重測（US3 / US6 / #361；#709 起不限已通過者）。

此處只驗**需要真 DB 才驗得了**的事：批次同時寫多張表（重置基準、進度）、
「不刪 attempt」這條只有真資料才驗得到的保證、以及對象的範圍（作答過的在籍學員）。

## 為什麼這條路徑不能重用 `reset_retry`

`tracking/rules.can_reset_retry` 在 `is_passed=True` 時回 `False`（理由：「他已經通過了；
再考只有機會把成績弄低」）——而本功能的對象**包含已通過的學員**，兩者前提相反。
⛔ 不可為了重用而放寬那個守門，它保護的是教師手動重置（US9 AC 6）。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
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
from app.et.course.stage_apply import apply_stage
from app.et.course.stage_repository import EtCourseStageRepository
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptM, EtQuizRetryReset
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


async def _apply(db, course_id: int, uid: str) -> None:
    """套用暫存區——**直接呼叫 `apply_stage`，繞過「更新」端點的發布檢核**。

    🔴 #631 之後「要求重測」不在編輯當下執行，而是延到按「更新」（2026-10-17 使用者
    裁示：在編輯當下執行的話，學員被退回的那一刻新題目還沒生效，他重考的是剛通過的
    同一份舊題）。所以本檔的每條測試都要經過套用才驗得到結果。

    ⚠️ 繞過端點是刻意的：本檔的課程以 DB 直寫建成，沒有標籤、沒有教材、配分也不是
    100，過不了那十項發布檢核。本檔要驗的是**重測這個副作用**，不是檢核——檢核由
    `test_et_course_stage.py::TestUpdateEndpoint` 守著。
    """
    repo = EtCourseStageRepository()
    course = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
    operator = OperatorInfo(user_id=uid)
    nodes = await repo.load_tree(db, course_id)
    await apply_stage(db, course=course, nodes=nodes, operator=operator)
    # ⚠️ **`clear` 要自己補**：它是 `update_published` 的一步，不在 `apply_stage` 裡面。
    # 少了它，暫存列會留著，下一輪編輯讀到的是上一輪推進過的版號，而送出的是活表版號
    # ⇒ 409，紅的理由與測試要驗的事情無關（2026-10-17 實際踩到）。
    await repo.clear(db, course_id, operator, stage_ids=[n.stage_id for n in nodes])


async def _save_and_apply(client, db, teacher: str, course_id: int, response) -> None:
    """教師存檔之後按「更新」——#631 之後**兩步才完整**。

    勾「要求重測」在編輯當下只是記下意圖（寄在測驗暫存節點的 payload 上），真正把學員
    退回未通過延到套用當下。本檔多數測試驗的是「退回之後怎樣」，所以一律補上這一步。

    「套用之前學員完全不動」由 `test_按更新之前學員狀態完全不動` 單獨釘住——放進本
    helper 的話，每條測試都會順便驗它，而那會讓它在某天失效時**沒有任何一條專門紅**。
    """
    assert response.status_code in (200, 201, 204), response.text
    await _apply(db, course_id, teacher)


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


class TestAffectedCount:
    """確認框要寫出受影響人數，否則教師無從判斷該選是或否。"""

    async def test_測驗詳細帶出受影響人數(self, client, db):
        # #709：對象是「作答過」的在籍學員，不限已通過；從未作答者本來就是滿額次數、
        # 也沒有舊成績，不計入。
        teacher = await _user(db, "ZTT010")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS010", course_id=cid, item_id=item_id, quiz_id=qid)
        await _passed_student(db, uid="ZTS011", course_id=cid, item_id=item_id, quiz_id=qid)
        failed = await _user(db, "ZTS012", roles=(ROLE_STUDENT,))
        await _enroll(db, failed, cid)
        await _attempt(db, user_id=failed, course_id=cid, quiz_id=qid, no=1, score=30, is_pass=False)
        never = await _user(db, "ZTS014", roles=(ROLE_STUDENT,))
        await _enroll(db, never, cid)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["affected_count"] == 3, "已通過 2 位＋未通過 1 位；從未作答者不計入"

    async def test_非擁有者看不到人數(self, client, db):
        # 比照同一回應既有的答案遮蔽：非擁有者可讀題目，但看不到這門課的學員統計。
        owner = await _user(db, "ZTT013")
        other = await _user(db, "ZTT014")
        cid, item_id, qid = await _course_with_quiz(db, owner)
        await _passed_student(db, uid="ZTS013", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(other))
        assert r.status_code == 200, r.text
        assert r.json()["affected_count"] is None, "非擁有者應拿到 None 而非 0——0 是錯誤資訊"


class TestRetestPendingVisibility:
    """勾選之後、按「更新」之前，教師看得見那筆要求嗎（2026-10-18 security review M-1）。

    🔴 看不見的後果不是「少一個提示」，而是**靜默撤銷**：旗標寄在測驗暫存節點的 payload
    上，而 `update_settings` 會依本次送來的 `require_retest` 覆寫它（那一支刻意如此
    ——測驗設定頁就是那個勾選框的所在地）。教師第二次進來只是改個錯字，畫面若顯示
    未勾，他按「僅儲存」就把十分鐘前的決定一起撤了，全程沒有任何訊息。
    """

    async def test_勾選後詳細頁回報待生效(self, client, db):
        teacher = await _user(db, "ZTT030")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS030", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()
        before = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert before.json()["require_retest_pending"] is False, "前置：還沒勾"

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        assert r.status_code == 204, r.text

        after = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert after.json()["require_retest_pending"] is True, "勾過就要讀得回來，否則下一次存檔會靜默清掉它"

    async def test_套用之後不再是待生效(self, client, db):
        """正向錨點：少了它，把那一欄寫死成 `True` 也會讓上一條通過。

        套用時重測已經執行完畢，暫存區隨之清空——「待生效」這個狀態不該留下來。
        """
        teacher = await _user(db, "ZTT031")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS031", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()
        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        after = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))

        assert after.json()["require_retest_pending"] is False

    async def test_改題路徑勾選後詳細頁也回報待生效(self, client, db):
        """#767 A1：使用者實測——改題時選「儲存並要求重測」、不按更新再改另一題，視窗沒有出現
        「已有一筆待生效的重測要求」。上一條只驗了測驗設定那一支。"""
        teacher = await _user(db, "ZTT032")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS032", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = {
            "question_type": "SINGLE",
            "stem": "輸血前應核對幾項資訊？",
            "points": 10,
            "options": [
                {"option_text": "兩項", "is_correct": False},
                {"option_text": "三項", "is_correct": True},
            ],
            "require_retest": True,
        }
        before = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert before.json()["require_retest_pending"] is False, "前置：還沒勾"
        r = await client.post(f"/api/et/quizzes/{qid}/questions", json=body, headers=_bearer(teacher))
        assert r.status_code in (200, 201), r.text

        after = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        assert after.json()["require_retest_pending"] is True

    async def test_修改既有題目勾選後詳細頁也回報待生效(self, client, db):
        teacher = await _user(db, "ZTT033")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS033", course_id=cid, item_id=item_id, quiz_id=qid)
        now = utcnow()
        live_q = EtQuestion(
            quiz_id=qid,
            question_type="SINGLE",
            stem="既有題目",
            points=100,
            sort_order=1,
            version=0,
            created_user=teacher,
            created_date=now,
            deleted=0,
        )
        db.add(live_q)
        await db.flush()
        for i, (text, ok) in enumerate((("甲", True), ("乙", False)), start=1):
            db.add(
                EtOption(
                    question_id=live_q.question_id,
                    option_text=text,
                    is_correct=ok,
                    sort_order=i,
                    created_user=teacher,
                    created_date=now,
                    deleted=0,
                )
            )
        await db.commit()
        detail = (await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))).json()
        assert detail["require_retest_pending"] is False, "前置：還沒勾"
        question = detail["questions"][0]
        body = {
            "question_type": question["question_type"],
            "stem": question["stem"] + "（改）",
            "points": question["points"],
            "options": [{"option_text": o["option_text"], "is_correct": o["is_correct"]} for o in question["options"]],
            "version": question["version"],
            "require_retest": True,
        }
        r = await client.put(f"/api/et/questions/{question['question_id']}", json=body, headers=_bearer(teacher))
        assert r.status_code in (200, 204), r.text

        after = (await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))).json()
        assert after["require_retest_pending"] is True


class TestRequireRetestOnQuizChange:
    async def test_按更新之前學員狀態完全不動(self, client, db):
        """🔴 #631 的核心保證（2026-10-17 使用者裁示）：勾選只是**記下意圖**。

        在編輯當下就執行的話，學員被退回未通過的那一刻**新題目還沒生效**——他去重考，
        考的是剛剛才通過的同一份舊題。副作用必須跟著「學員看得到了」一起發生，與 #303
        的通知改到「更新」當下寄是同一個道理。

        ⚠️ 本條是 `_save_and_apply` 的對照組：那個 helper 把「存檔 + 更新」併成一步，
        所以其餘測試都跨過了這個中間狀態。少了這一條，把意圖改回「編輯當下就執行」
        **不會有任何測試變紅**。
        """
        teacher = await _user(db, "ZTT000")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS000", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()
        before = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert before[2] is True, "前置條件：學員此刻是已完成"

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))

        assert r.status_code == 204, r.text
        assert await _facts(db, uid=stu, quiz_id=qid, item_id=item_id) == before, "按更新之前不得動到學員"

        await _apply(db, cid, teacher)

        after = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert after[1] == 1 and after[2] is False, "按更新之後才退回"

    async def test_選是時已通過學員次數歸零且完成狀態清除(self, client, db):
        teacher = await _user(db, "ZTT001")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS001", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

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
        await _save_and_apply(client, db, teacher, cid, r)

        attempts, _, _ = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert attempts == 2, "兩次 attempt 都必須留著（軟刪除也不行）"

    async def test_選否時學員狀態完全不動(self, client, db):
        teacher = await _user(db, "ZTT003")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS003", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=False)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

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
        await _save_and_apply(client, db, teacher, cid, r)

        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 2, "兩位受影響的學員應各排入一封；逐人一封而非合批（範本含 {USER_NAME}）"

        # 批次寫入（`add_retry_resets` / `set_item_completed_bulk`）要對**每一位**生效。
        # 只驗信件數不夠：批次 INSERT 若只寫進第一筆，信照樣會寄兩封。
        for uid in ("ZTS005", "ZTS006"):
            _, resets, done = await _facts(db, uid=uid, quiz_id=qid, item_id=item_id)
            assert (resets, done) == (1, False), f"{uid} 的重置基準與完成旗標都要生效"

        # 🔴 每封信的內文要是**收件人自己**的姓名。
        #
        # 範本含 `{USER_NAME}`，而平台 `send_email` 對整批收件人**只渲染一次**——若有人
        # 把逐人迴圈「優化」成合批，信件數仍是 2、上面的斷言照樣過，但兩封信會寫同一
        # 個人的名字。目前只靠迴圈結構保證，這條是唯一會在那時變紅的測試。
        mails = (await db.execute(select(DpEmailLog).where(DpEmailLog.status == "PENDING"))).scalars().all()
        for mail in mails:
            uid = mail.recipient.split("@")[0]
            assert f"測試{uid}" in mail.body, f"寄給 {mail.recipient} 的信內文必須是他自己的姓名"
            # #709：收件人不限已通過者，內文不得再寫「要求已通過的學員」（migration d5a7e3c91f48）
            assert "教師要求重新測驗" in mail.body
            assert "已通過的學員" not in mail.body

    async def test_新增題目也能要求重測(self, client, db):
        teacher = await _user(db, "ZTT006")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS007", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = {
            "question_type": "SINGLE",
            "stem": "輸血前應核對幾項資訊？",
            "points": 10,
            "options": [
                {"option_text": "兩項", "is_correct": False},
                {"option_text": "三項", "is_correct": True},
            ],
            "require_retest": True,
        }
        r = await client.post(f"/api/et/quizzes/{qid}/questions", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        _, resets, done = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert (resets, done) == (1, False), "新增題目是題目內容變更，應能觸發重測"

    async def test_刪除題目也能要求重測且不刪作答明細(self, client, db):
        """⚠️ 本測驗**必須先有兩題**才刪得掉一題（#410）。

        `_course_with_quiz` 建的是零題測驗，原本只加一題就刪，而 #410 起已發布課程的
        測驗不得被刪到 0 題（409 `ET_QUESTION_005`）。加兩題刪一題保住本條真正要驗的
        東西——「刪題也算題目內容變更、應能觸發重測」與「不得連帶刪 attempt」——
        而不是去驗那道新守門（那由 `test_et_quiz.py` 的四條負責）。
        """
        teacher = await _user(db, "ZTT007")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS008", course_id=cid, item_id=item_id, quiz_id=qid)
        question_id = None
        for stem in ("留下的題目", "待刪除的題目"):
            add = await client.post(
                f"/api/et/quizzes/{qid}/questions",
                json={
                    "question_type": "SINGLE",
                    "stem": stem,
                    "points": 10,
                    "options": [
                        {"option_text": "甲", "is_correct": True},
                        {"option_text": "乙", "is_correct": False},
                    ],
                },
                headers=_bearer(teacher),
            )
            assert add.status_code == 201, add.text
            question_id = add.json()["question_id"]
        await db.commit()

        r = await client.delete(f"/api/et/questions/{question_id}?require_retest=true", headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        attempts, resets, done = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert (resets, done) == (1, False), "刪除題目是題目內容變更，應能觸發重測"
        assert attempts == 1, "⛔ 刪題不得連帶刪除 attempt（#279 裁示 Q2=C）"

    async def test_排序不觸發重測(self, client, db):
        # 只改呈現順序、不改題目與配分；而且 attempt 有 question_order 快照，
        # 舊紀錄本來就不受影響——為此要全班重考沒有道理。
        teacher = await _user(db, "ZTT008")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS009", course_id=cid, item_id=item_id, quiz_id=qid)
        ids = []
        for stem in ("第一題", "第二題"):
            add = await client.post(
                f"/api/et/quizzes/{qid}/questions",
                json={
                    "question_type": "SINGLE",
                    "stem": stem,
                    "points": 10,
                    "options": [
                        {"option_text": "甲", "is_correct": True},
                        {"option_text": "乙", "is_correct": False},
                    ],
                },
                headers=_bearer(teacher),
            )
            ids.append(add.json()["question_id"])
        await db.commit()

        # 排序帶的是**測驗層** version，而新增題目會把它推進，故現取。
        detail = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(teacher))
        r = await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            json={"question_ids": list(reversed(ids)), "version": detail.json()["version"]},
            headers=_bearer(teacher),
        )
        await _save_and_apply(client, db, teacher, cid, r)

        _, resets, done = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert (resets, done) == (0, True), "排序不是內容變更，不該把全班的通過紀錄清掉"

    async def test_重複儲存不會重複重置也不會重複寄信(self, client, db):
        # 🔴 這條釘住「最近一次要求重測之後有作答」這個語意（#709 前為「目前算通過」）。
        #
        # 若改成單純的「曾作答」／「曾及格」，該值重置後不會下降：確認框會
        # 一直跳、教師每按一次就再寄 N 封信、再寫 N 列 append-only 的重置基準。
        # 「手滑連按三次 → 全班收三封」很容易發生。
        teacher = await _user(db, "ZTT030")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS030", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        for round_no in (1, 2):
            # ⚠️ 每一輪都要「存檔 + 更新」才算一次完整的儲存（#631）。少了更新，第二輪
            # 的 `_settings_body` 會讀到未被套用的活表版號而 409——紅的理由就與本條要驗的
            # 「第二次不該重複重置」無關了。
            body = await _settings_body(db, qid, pass_score=80 + round_no, require_retest=True)
            r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
            assert r.status_code == 204, f"第 {round_no} 次儲存：{r.text}"
            await _apply(db, cid, teacher)

        _, resets, done = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert resets == 1, "第二次儲存時該學員在重測後尚未作答，不應再寫一列基準"
        assert done is False
        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 1, "第二次儲存不應再寄一封——他已經被要求重測了"

    async def test_已被移出課程的學員不受影響也不收信(self, client, db):
        # 🔴 本功能的安全不變量之一。`mark_removed` 只設 `IS_REMOVED`、不動 attempt 與
        # progress，所以少了那道 JOIN 過濾，一位已離開課程的人會被寫重置基準、清完成
        # 旗標，還收到一封「請重新測驗」的信。
        #
        # ⚠️ 少了這條測試，那個 JOIN 在任何一次「這個 join 好像多餘」的重構中被拿掉，
        # CI 會全綠，症狀只有「被移出課程的人莫名收到信」——在正式環境極難發現。
        teacher = await _user(db, "ZTT020")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        gone = await _passed_student(db, uid="ZTS020", course_id=cid, item_id=item_id, quiz_id=qid)
        enrollment = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == gone, EtEnrollment.course_id == cid)
        )
        enrollment.is_removed = True
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        _, resets, done = await _facts(db, uid=gone, quiz_id=qid, item_id=item_id)
        assert (resets, done) == (0, True), "已移出課程者不應被寫入基準、不應被清除完成狀態"
        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 0, "已移出課程者不應收到「請重新測驗」的信"

    async def test_非擁有者無法觸發批次重置(self, client, db):
        # 🔴 本功能的安全不變量之二。批次會改動**多位學員**的學習狀態，而守門只有
        # 呼叫端的 `ensure_owner`。非擁有者除了被擋下之外，學員狀態必須完全沒動。
        owner = await _user(db, "ZTT021")
        other = await _user(db, "ZTT022")
        cid, item_id, qid = await _course_with_quiz(db, owner)
        stu = await _passed_student(db, uid="ZTS021", course_id=cid, item_id=item_id, quiz_id=qid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(other))
        assert r.status_code == 403, r.text

        facts = await _facts(db, uid=stu, quiz_id=qid, item_id=item_id)
        assert facts == (1, 0, True), "被擋下時學員狀態必須完全沒動"

    async def test_未通過的學員也被要求重測(self, client, db):
        # #709 SA 裁示（推翻 #361 只限已通過者）：要求重測是舊題目有問題、責任在出題方，
        # 未通過者的次數可能已被錯題耗掉——所有作答過的人都拿到同樣的新一輪與通知。
        teacher = await _user(db, "ZTT004")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        failed = await _user(db, "ZTS004", roles=(ROLE_STUDENT,))
        await _enroll(db, failed, cid)
        await _attempt(db, user_id=failed, course_id=cid, quiz_id=qid, no=1, score=40, is_pass=False)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        attempts, resets, _ = await _facts(db, uid=failed, quiz_id=qid, item_id=item_id)
        assert (attempts, resets) == (1, 1), "未通過者也要寫入重測起點（次數歸零）"
        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 1, "未通過者也要收到通知信"

    async def test_從未作答的學員不受影響(self, client, db):
        # 本來就是滿額次數、也沒有舊成績——寫起點與寄信都沒有意義。
        teacher = await _user(db, "ZTT009")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        await _passed_student(db, uid="ZTS015", course_id=cid, item_id=item_id, quiz_id=qid)
        never = await _user(db, "ZTS016", roles=(ROLE_STUDENT,))
        await _enroll(db, never, cid)
        await db.commit()

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        # 正向錨點：同一次儲存確實有對作答過的人生效，上面的 0 才有意義
        assert (await _facts(db, uid="ZTS015", quiz_id=qid, item_id=item_id))[1] == 1
        assert (await _facts(db, uid=never, quiz_id=qid, item_id=item_id))[1] == 0, "從未作答者不應寫入起點"
        pending = await db.scalar(select(func.count()).select_from(DpEmailLog).where(DpEmailLog.status == "PENDING"))
        assert pending == 1, "只寄給作答過的那位"


class TestPassedDefinitionAfterRetest:
    """#610：要求重測後，系統各處的「已通過」不得再以「**曾**及格」判定。

    ## 這不是放寬 `can_reset_retry`

    該規則的運算式未變（`has_attempt and not is_passed and used > max_retry`），
    改的是呼叫端算出來的 `is_passed`——它原本數「所有輪次是否曾及格」，現在改為
    **在最近一次重置基準之後**是否仍有及格紀錄（`tracking/repository` 的 `#610` 段）。

    ⛔ 教師仍不可對「目前算通過」的學員按重置（見 `test_未經重置的及格者仍不可重置`
    與 `test_重測又通過後恢復為不可重置` 兩條正向錨點）。
    """

    @staticmethod
    def _reset_url(course_id: int, user_id: str, quiz_id: int) -> str:
        return f"/api/et/courses/{course_id}/students/{user_id}/quizzes/{quiz_id}/retry-reset"

    async def test_重測不及格且次數用盡時教師可重置(self, client, db) -> None:
        """🔴 本 issue 的核心：少了這條，學員會**永久卡在課程裡**。

        #361 起未及格的測驗會擋住後續項目，而教師又因「曾及格」而無法重置——
        沒有任何補救管道。
        """
        teacher = await _user(db, "ZTT610A")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610A", course_id=cid, item_id=item_id, quiz_id=qid)

        # 教師改題並要求重測 → 寫入重置基準、清掉完成旗標
        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        r = await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _save_and_apply(client, db, teacher, cid, r)

        # 學員重測三次（max_retry=2 → 本輪配額 3 次）全部不及格，次數用盡
        for no in (2, 3, 4):
            await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=no, score=10, is_pass=False)

        r = await client.post(self._reset_url(cid, stu, qid), headers=_bearer(teacher))

        assert r.status_code == 200, f"重測不及格且次數用盡者必須可重置，實得 {r.status_code} {r.text}"

    async def test_剛要求重測尚未重考時仍不可重置(self, client, db) -> None:
        """⚠️ 勾「要求重測」本身**不會**讓重置變可按。

        此時本輪配額剛歸零、一次都還沒用，被 `used > max_retry` 擋下——擋的理由從
        「已及格」換成「次數未用盡」，但結果相同。少了這條，看不出我只改了判定、
        沒有放寬規則。
        """
        teacher = await _user(db, "ZTT610B")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610B", course_id=cid, item_id=item_id, quiz_id=qid)

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))

        r = await client.post(self._reset_url(cid, stu, qid), headers=_bearer(teacher))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_002"

    async def test_未經重置的及格者仍不可重置(self, client, db) -> None:
        """正向錨點：沒有要求重測時，行為完全不變。

        少了這條，把 `is_passed` 一律算成 False 也會讓上面那條通過——而那正是擋牌
        （`quiz/service.py`「不要放寬 can_reset_retry」）要防的事。
        """
        teacher = await _user(db, "ZTT610C")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610C", course_id=cid, item_id=item_id, quiz_id=qid)
        # 把配額用完，確保被擋下的理由只可能是「已及格」
        for no in (2, 3):
            await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=no, score=10, is_pass=False)

        r = await client.post(self._reset_url(cid, stu, qid), headers=_bearer(teacher))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_TRACK_002"

    async def test_重測又通過後恢復為不可重置(self, client, db) -> None:
        """正向錨點之二：基準**之後**有及格紀錄者，仍是「目前算通過」。"""
        teacher = await _user(db, "ZTT610D")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610D", course_id=cid, item_id=item_id, quiz_id=qid)

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))

        # 重測：前兩次不及格、第三次通過 → 配額用盡但目前算通過
        await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=2, score=10, is_pass=False)
        await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=3, score=10, is_pass=False)
        await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=4, score=95, is_pass=True)

        r = await client.post(self._reset_url(cid, stu, qid), headers=_bearer(teacher))

        assert r.status_code == 409, "基準後又通過者仍算目前通過，不可重置"
        assert r.json()["error_code"] == "ET_TRACK_002"

    async def test_要求重測後_ET02_區塊2不再顯示已及格(self, client, db) -> None:
        """🔴 issue 重現步驟第 5 步：教師在 ET02 看到「已及格」、重置鈕停用。

        這一格由 `tracking/service._to_quiz_row` 的 `is_passed` 決定，而它**早就收到
        `reset_base`**、只用在次數上。變異檢查實測：把該行改回 `any(bool(a.is_pass)
        for a in attempts)`，上面那四條與 `test_et_tracking.py` 全組**都不會紅**
        ——這一格原本完全沒有測試覆蓋。
        """
        teacher = await _user(db, "ZTT610F")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610F", course_id=cid, item_id=item_id, quiz_id=qid)

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _apply(db, cid, teacher)  # #631：按「更新」才真的退回
        await _attempt(db, user_id=stu, course_id=cid, quiz_id=qid, no=2, score=10, is_pass=False)

        r = await client.get(f"/api/et/courses/{cid}/attempt-overview", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        rows = [s_ for s_ in r.json()["students"] if s_["user_id"] == stu]
        assert rows, "該學員應出現在區塊 2"
        quiz_row = next(q for q in rows[0]["quizzes"] if q["quiz_id"] == qid)
        assert quiz_row["is_passed"] is False, "要求重測後，ET02 不得再顯示已及格"
        # 正向錨點：本輪已用次數確實從 0 起算（證明重置基準有被讀到、不是整欄恆 False）
        assert quiz_row["used_attempts"] == 1

    async def test_要求重測後引導頁不再顯示已及格(self, client, db) -> None:
        """另一半症狀：ET07 引導頁的綠色橫幅仍顯示舊分數「— 已及格」。

        學員看到「已及格」卻被鎖在後面章節外，兩者互相矛盾。來源是
        `attempt/repository.score_summary` 的第三個回傳值（其 docstring 自己寫著
        「是否**曾**及格」）。

        📌 #709（2026-10-18 裁示）起最高分只計重測後一輪，重測後尚未重考時 `best_score`
        為 `None`（見 `test_et_attempt_rounds.py`）；本條只守「不再顯示已及格」。
        """
        teacher = await _user(db, "ZTT610E")
        cid, item_id, qid = await _course_with_quiz(db, teacher)
        stu = await _passed_student(db, uid="ZTS610E", course_id=cid, item_id=item_id, quiz_id=qid)

        body = await _settings_body(db, qid, pass_score=85, require_retest=True)
        await client.put(f"/api/et/quizzes/{qid}", json=body, headers=_bearer(teacher))
        await _apply(db, cid, teacher)  # #631：按「更新」才真的退回

        r = await client.get(f"/api/et/quizzes/{qid}/intro", headers=_bearer(stu))

        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["is_passed"] is False, "要求重測後不得再顯示已及格"
        # 正向錨點：最近一次成績仍照實顯示（證明確實讀到了舊輪的作答）
        assert payload["last_score"] is not None
