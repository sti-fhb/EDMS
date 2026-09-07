"""ET06 測驗作答整合測試（US6 / #279）。

計分公式、剩餘次數、逾時判定已於 `tests/unit/et/test_attempt_rules.py` 以**純函式**
驗完。此處只驗**需要真 DB 才驗得了**的事：

1. 快照真的凍結了，且教師事後改題 / 刪題不影響已建立的 attempt
2. 續作（SA 裁示 Q1 = A）確實回同一筆、不吃次數
3. 及格 → 項目完成 → 下一項解鎖這條鏈接得起來
4. **作答中不外送 `is_correct`**——本檔的安全核心
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    ATTEMPT_SUBMITTED,
    ATTEMPT_TIMEOUT,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_MULTIPLE,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuizAttemptD, EtQuizAttemptM
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT) -> str:
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
    db.add(EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()
    return user_id


async def _course_with_quiz(client, db, teacher: str, *, code: str, extra_chapter: bool = False) -> dict:
    """建課程 → 第 1 章（測驗項目）→ 可選的第 2 章（教材項目），發布並開放。

    測驗放**第 1 章第 1 項**，故一開始就是解鎖的——本檔多數測試不想被解鎖規則干擾。
    """
    created = await client.post(_COURSES, json={"course_name": "採血作業教育"}, headers=_bearer(teacher))
    course_id = created.json()["course_id"]
    ch = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
    )
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考"},
        headers=_bearer(teacher),
    )
    result = {
        "course_id": course_id,
        "quiz_item_id": item.json()["item_id"],
        "quiz_id": item.json()["quiz_id"],
        "next_item_id": None,
    }
    if extra_chapter:
        ch2 = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(teacher)
        )
        item2 = await client.post(
            f"/api/et/chapters/{ch2.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL},
            headers=_bearer(teacher),
        )
        result["next_item_id"] = item2.json()["item_id"]
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(
            status=COURSE_PUBLISHED,
            invitation_code=code,
            # 已發布但 `open_start_at` 為 NULL 的課程對學員完全不可見
            open_start_at=utcnow() - timedelta(hours=1),
        )
    )
    await db.flush()
    return result


async def _add_question(client, teacher: str, quiz_id: int, *, qtype=QUESTION_SINGLE, points=100, options=None) -> dict:
    body = {
        "question_type": qtype,
        "stem": "題幹",
        "points": points,
        "options": options
        if options is not None
        else [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
    }
    r = await client.post(f"/api/et/quizzes/{quiz_id}/questions", json=body, headers=_bearer(teacher))
    assert r.status_code == 201, r.text
    return r.json()


async def _enroll(db, user_id: str, course_id: int) -> None:
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=utcnow(),
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


def _answer_url(attempt_id: int, question_id: int) -> str:
    return f"/api/et/attempts/{attempt_id}/answers/{question_id}"


class TestStartAttempt:
    async def test_開始作答凍結四項快照(self, client, db) -> None:
        """AC 3：題目順序 / 選項順序 / 及格分數 / 時限皆於 `STARTED_AT` 凍結。"""
        teacher = await _user(db, "t_att01", ROLE_TEACHER)
        student = await _user(db, "s_att01")
        course = await _course_with_quiz(client, db, teacher, code="32000001")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])

        r = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(student))

        assert r.status_code == 201, r.text
        attempt = await db.scalar(select(EtQuizAttemptM).where(EtQuizAttemptM.attempt_id == r.json()["attempt_id"]))
        assert json.loads(attempt.question_order), "題目順序快照為空"
        assert json.loads(attempt.option_order), "選項順序快照為空"
        assert attempt.pass_score_snapshot == 80
        assert attempt.attempt_no == 1
        detail = await db.scalar(select(EtQuizAttemptD).where(EtQuizAttemptD.attempt_id == attempt.attempt_id))
        assert detail.stem_snapshot == "題幹"
        assert detail.points_snapshot == 100
        assert json.loads(detail.options_snapshot)[0]["is_correct"] in (True, False)

    async def test_作答中不外送正確答案(self, client, db) -> None:
        """**本檔的安全核心**：正確答案存在快照裡，但作答中送出去等於印在網頁原始碼上。

        wireframe 的洗牌設計正是為了讓答案不可預測；把 `is_correct` 一起送出會讓那個
        設計完全失效，而畫面上看不出任何異常。
        """
        teacher = await _user(db, "t_att02", ROLE_TEACHER)
        student = await _user(db, "s_att02")
        course = await _course_with_quiz(client, db, teacher, code="32000002")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])

        r = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(student))

        assert "is_correct" not in r.text, "作答中的回應含正確答案"

    async def test_已有進行中的作答時續作而非開新(self, client, db) -> None:
        """#279 SA 裁示 Q1 = A。

        斷線 / 當機 / 誤觸上一頁都不是學員的選擇，而作廢的代價是一次作答次數
        （`MAX_RETRY` 常只有 1~3 次）。時間照扣已經是對中斷的懲罰。
        """
        teacher = await _user(db, "t_att03", ROLE_TEACHER)
        student = await _user(db, "s_att03")
        course = await _course_with_quiz(client, db, teacher, code="32000003")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        first = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)
        # 先答一題，確認續作時答案還在
        await client.put(
            _answer_url(first.json()["attempt_id"], q["question_id"]),
            json={"selected_options": [q["options"][0]["option_id"]]},
            headers=h,
        )

        again = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)

        assert again.status_code == 201, again.text
        assert again.json()["attempt_id"] == first.json()["attempt_id"], "開了新的 attempt"
        assert again.json()["resumed"] is True
        assert again.json()["questions"][0]["selected_options"] == [q["options"][0]["option_id"]]
        assert (
            await db.scalar(
                select(EtQuizAttemptM.attempt_no).where(EtQuizAttemptM.attempt_id == first.json()["attempt_id"])
            )
            == 1
        )

    async def test_未解鎖的測驗不可開始(self, client, db) -> None:
        """測驗在第 2 章，第 1 章未完成 → 404（比照 #274 的第 4 道守門）。"""
        teacher = await _user(db, "t_att04", ROLE_TEACHER)
        student = await _user(db, "s_att04")
        created = await client.post(_COURSES, json={"course_name": "課"}, headers=_bearer(teacher))
        cid = created.json()["course_id"]
        ch1 = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
        await client.post(
            f"/api/et/chapters/{ch1.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL},
            headers=_bearer(teacher),
        )
        ch2 = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(teacher))
        quiz_item = await client.post(
            f"/api/et/chapters/{ch2.json()['chapter_id']}/items",
            json={"item_type": ITEM_QUIZ, "title": "小考"},
            headers=_bearer(teacher),
        )
        await _add_question(client, teacher, quiz_item.json()["quiz_id"], points=100)
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == cid)
            .values(status=COURSE_PUBLISHED, invitation_code="32000004", open_start_at=utcnow() - timedelta(hours=1))
        )
        await _enroll(db, student, cid)
        await db.commit()

        r = await client.post(f"/api/et/quizzes/{quiz_item.json()['quiz_id']}/attempts", headers=_bearer(student))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_ATTEMPT_001"

    async def test_非在籍者不可開始(self, client, db) -> None:
        teacher = await _user(db, "t_att05", ROLE_TEACHER)
        outsider = await _user(db, "s_att05")
        course = await _course_with_quiz(client, db, teacher, code="32000005")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await db.commit()

        r = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(outsider))

        assert r.status_code == 404, r.text


class TestGrading:
    async def test_單選答對得滿分並解鎖下一章(self, client, db) -> None:
        """AC 8 + AC 12——閱卷、及格判定、回寫項目完成、下一章解鎖一整條鏈。"""
        teacher = await _user(db, "t_att06", ROLE_TEACHER)
        student = await _user(db, "s_att06")
        course = await _course_with_quiz(client, db, teacher, code="32000006", extra_chapter=True)
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert r.status_code == 200, r.text
        assert float(r.json()["score"]) == 100.0
        assert r.json()["is_pass"] is True
        assert r.json()["status"] == ATTEMPT_SUBMITTED
        # 及格 → 項目完成 → 第 2 章解鎖
        completed = await db.scalar(
            select(EtProgress.is_completed).where(
                EtProgress.user_id == student, EtProgress.item_id == course["quiz_item_id"]
            )
        )
        assert completed is True
        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        items = {i["item_id"]: i for c in structure.json()["chapters"] for i in c["items"]}
        assert items[course["next_item_id"]]["locked"] is False

    async def test_多選部分計分依快照(self, client, db) -> None:
        """`spec_us6` 場景 14：應選 3、配分 100、答對 2、誤選 1 → `(2−1)÷3×100` = 33.33。"""
        teacher = await _user(db, "t_att07", ROLE_TEACHER)
        student = await _user(db, "s_att07")
        course = await _course_with_quiz(client, db, teacher, code="32000007")
        q = await _add_question(
            client,
            teacher,
            course["quiz_id"],
            qtype=QUESTION_MULTIPLE,
            points=100,
            options=[
                {"option_text": "A", "is_correct": True},
                {"option_text": "B", "is_correct": True},
                {"option_text": "C", "is_correct": True},
                {"option_text": "D", "is_correct": False},
            ],
        )
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        by_text = {o["option_text"]: o["option_id"] for o in q["options"]}
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]),
            json={"selected_options": [by_text["A"], by_text["B"], by_text["D"]]},
            headers=h,
        )

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert float(r.json()["score"]) == pytest.approx(33.33)
        assert r.json()["is_pass"] is False
        assert r.json()["questions"][0]["outcome"] == "PARTIAL"

    async def test_明細強制帶正確答案(self, client, db) -> None:
        """AC 11：**提交後**才送正確答案，且無教師可關閉之選項。"""
        teacher = await _user(db, "t_att08", ROLE_TEACHER)
        student = await _user(db, "s_att08")
        course = await _course_with_quiz(client, db, teacher, code="32000008")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        options = r.json()["questions"][0]["options"]
        assert any(o["is_correct"] for o in options), "明細未帶正確答案"
        assert all("selected" in o for o in options)

    async def test_逾時提交照常閱卷並記為_timeout(self, client, db) -> None:
        """AC 6：逾時**不拒收**——拒收等於沒收學員已經寫好的考卷。"""
        teacher = await _user(db, "t_att09", ROLE_TEACHER)
        student = await _user(db, "s_att09")
        course = await _course_with_quiz(client, db, teacher, code="32000009")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await client.put(
            f"/api/et/quizzes/{course['quiz_id']}",
            json={"quiz_name": "小考", "pass_score": 80, "time_limit_min": 10, "max_retry": 3, "version": 0},
            headers=_bearer(teacher),
        )
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )
        # 把開始時間往前推 20 分鐘，超過 10 分鐘的時限
        await db.execute(
            update(EtQuizAttemptM)
            .where(EtQuizAttemptM.attempt_id == attempt["attempt_id"])
            .values(started_at=utcnow() - timedelta(minutes=20))
        )
        await db.flush()

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["status"] == ATTEMPT_TIMEOUT
        assert float(r.json()["score"]) == 100.0, "逾時仍須照常計分"

    async def test_重複提交被擋(self, client, db) -> None:
        teacher = await _user(db, "t_att10", ROLE_TEACHER)
        student = await _user(db, "s_att10")
        course = await _course_with_quiz(client, db, teacher, code="32000010")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        await db.commit()

        again = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert again.status_code == 409, again.text
        assert again.json()["error_code"] == "ET_ATTEMPT_003"


class TestSnapshotIsolation:
    async def test_教師改配分不影響進行中的作答(self, client, db) -> None:
        """AC 15：閱卷讀快照，不回頭查 `ET_QUESTION`。

        回頭查會讓「教師在學員作答期間改了配分」變成靜默算錯分，而學員拿到的是一個
        看起來正常的分數。
        """
        teacher = await _user(db, "t_att11", ROLE_TEACHER)
        student = await _user(db, "s_att11")
        course = await _course_with_quiz(client, db, teacher, code="32000011")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )
        # 教師把配分改成 50（學員作答中）
        await client.put(
            f"/api/et/questions/{q['question_id']}",
            json={"question_type": QUESTION_SINGLE, "stem": "改過的題幹", "points": 50, "options": q["options"]},
            headers=_bearer(teacher),
        )

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert float(r.json()["score"]) == 100.0, "依快照應得 100，讀當前值會變 50"
        assert r.json()["questions"][0]["stem"] == "題幹", "題幹亦須為快照"

    async def test_教師刪題後歷次明細仍完整(self, client, db) -> None:
        """**#279 SA 裁示 Q2 = C 的迴歸測試**。

        連帶軟刪除 `ET_QUIZ_ATTEMPT_D` 會讓學員看到「總分 100、明細 0 題」這種自己
        對不起來的成績單——`ET_QUIZ_ATTEMPT_M.SCORE` 是閱卷當下凍結的，不因題目後來
        被刪而改變（也不該改）。
        """
        teacher = await _user(db, "t_att12", ROLE_TEACHER)
        student = await _user(db, "s_att12")
        course = await _course_with_quiz(client, db, teacher, code="32000012")
        q1 = await _add_question(client, teacher, course["quiz_id"], points=50)
        await _add_question(client, teacher, course["quiz_id"], points=50)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        submitted = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        assert len(submitted.json()["questions"]) == 2

        deleted = await client.delete(f"/api/et/questions/{q1['question_id']}", headers=_bearer(teacher))
        assert deleted.status_code == 204, deleted.text

        rows = list(
            await db.scalars(select(EtQuizAttemptD.deleted).where(EtQuizAttemptD.attempt_id == attempt["attempt_id"]))
        )
        assert rows == [0, 0], "刪題不得連帶軟刪除學員的作答明細（裁示 Q2 = C）"


class TestRetryLimit:
    async def test_次數用完回四零九(self, client, db) -> None:
        teacher = await _user(db, "t_att13", ROLE_TEACHER)
        student = await _user(db, "s_att13")
        course = await _course_with_quiz(client, db, teacher, code="32000013")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await client.put(
            f"/api/et/quizzes/{course['quiz_id']}",
            json={"quiz_name": "小考", "pass_score": 80, "time_limit_min": None, "max_retry": 0, "version": 0},
            headers=_bearer(teacher),
        )
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        # `MAX_RETRY = 0` → **只能作答 1 次**（不是不能作答）
        first = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)
        assert first.status_code == 201, first.text
        await client.post(f"/api/et/attempts/{first.json()['attempt_id']}/submit", headers=h)
        await db.commit()

        second = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)

        assert second.status_code == 409, second.text
        assert second.json()["error_code"] == "ET_ATTEMPT_002"

    async def test_引導頁回傳題數與剩餘次數(self, client, db) -> None:
        teacher = await _user(db, "t_att14", ROLE_TEACHER)
        student = await _user(db, "s_att14")
        course = await _course_with_quiz(client, db, teacher, code="32000014")
        await _add_question(client, teacher, course["quiz_id"], points=50)
        await _add_question(client, teacher, course["quiz_id"], points=50)
        await _enroll(db, student, course["course_id"])

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/intro", headers=_bearer(student))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["question_count"] == 2
        assert body["remaining_attempts"] == 4, "MAX_RETRY 預設 3 → 總可作答 4 次"
        assert body["can_start"] is True
        assert body["time_limit_min"] is None, "未設時限應為 null（不限時），不是 0"
        assert body["last_score"] is None


class TestAttemptOwnership:
    async def test_不可讀他人的作答(self, client, db) -> None:
        teacher = await _user(db, "t_att15", ROLE_TEACHER)
        owner = await _user(db, "s_att15a")
        other = await _user(db, "s_att15b")
        course = await _course_with_quiz(client, db, teacher, code="32000015")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, owner, course["course_id"])
        await _enroll(db, other, course["course_id"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(owner))).json()
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}", headers=_bearer(other))

        assert r.status_code == 404, r.text
