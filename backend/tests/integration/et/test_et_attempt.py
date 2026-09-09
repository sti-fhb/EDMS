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
    COURSE_CLOSED,
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
    async def test_單選答對得滿分並回寫項目完成(self, client, db) -> None:
        """AC 8：閱卷 → 及格判定 → 回寫 `ET_PROGRESS.IS_COMPLETED`。

        ⚠️ **不驗「因此解鎖下一章」**——`spec_us5` AC 12（測驗未及格阻擋解鎖）依 #279
        裁示 2 = C **尚未啟用**：`build_item_state` 目前仍讓測驗恆視為通過，因為
        「重置重考次數」（US9）未實作，掛上門檻會讓次數用盡的學員永久鎖死且無從補救。

        本測試因此只釘住「及格會寫進度」這件事——那是 `ET-9` 啟用門檻時的前提。
        """
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
        completed = await db.scalar(
            select(EtProgress.is_completed).where(
                EtProgress.user_id == student, EtProgress.item_id == course["quiz_item_id"]
            )
        )
        assert completed is True, "及格須回寫項目完成（側欄的打勾與日後的解鎖門檻都靠它）"
        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        items = {i["item_id"]: i for c in structure.json()["chapters"] for i in c["items"]}
        assert items[course["quiz_item_id"]]["completed"] is True, "側欄應顯示已完成"

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


class TestWriteGuards:
    """review 抓到的三道守門——都是「規則寫在別處但這裡沒接上」。"""

    async def test_逾時後不可再暫存答案(self, client, db) -> None:
        """**時限的唯一強制力**。

        `submit` 閱卷讀的是 `SELECTED_OPTIONS` 的當前值，而逾時只決定 `STATUS` 標成
        `TIMEOUT`——不影響計分。若暫存不擋逾時，學員可以關掉分頁、慢慢查完資料、回來
        逐題寫入再提交，照樣滿分，時限完全形同虛設。
        """
        teacher = await _user(db, "t_att16", ROLE_TEACHER)
        student = await _user(db, "s_att16")
        course = await _course_with_quiz(client, db, teacher, code="32000016")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await client.put(
            f"/api/et/quizzes/{course['quiz_id']}",
            json={"quiz_name": "小考", "pass_score": 80, "time_limit_min": 10, "max_retry": 3, "version": 0},
            headers=_bearer(teacher),
        )
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await db.execute(
            update(EtQuizAttemptM)
            .where(EtQuizAttemptM.attempt_id == attempt["attempt_id"])
            .values(started_at=utcnow() - timedelta(minutes=20))
        )
        await db.commit()

        r = await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]),
            json={"selected_options": [q["options"][0]["option_id"]]},
            headers=h,
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_ATTEMPT_005"

    async def test_課程關閉後不可開新作答(self, client, db) -> None:
        """#255 裁示 Q2「關閉 = 讀照舊、寫全停」+ `spec_us6` 場景 27。"""
        teacher = await _user(db, "t_att17", ROLE_TEACHER)
        student = await _user(db, "s_att17")
        course = await _course_with_quiz(client, db, teacher, code="32000017")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(student))

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_ATTEMPT_006"

    async def test_課程關閉時已在作答者仍可提交並計分(self, client, db) -> None:
        """場景 27 要保的那條窄縫——關閉當下已在作答的 attempt 不可被沒收。"""
        teacher = await _user(db, "t_att18", ROLE_TEACHER)
        student = await _user(db, "s_att18")
        course = await _course_with_quiz(client, db, teacher, code="32000018")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )
        # 作答中課程被關閉
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert r.status_code == 200, r.text
        assert float(r.json()["score"]) == 100.0
        assert r.json()["is_pass"] is True

    async def test_教師預覽不寫入學習進度(self, client, db) -> None:
        """#255 裁示 Q1（`learning/rules.py` 特別標了「給 ET-5b」的警告）。

        教師預覽完就出現在自己課程的完課統計裡，正是該裁示要避開的後果。
        """
        teacher = await _user(db, "t_att19", ROLE_TEACHER)
        course = await _course_with_quiz(client, db, teacher, code="32000019")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        h = _bearer(teacher)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["is_pass"] is True, "教師仍看得到自己的成績（預覽的用途）"
        completed = await db.scalar(
            select(EtProgress).where(EtProgress.user_id == teacher, EtProgress.item_id == course["quiz_item_id"])
        )
        assert completed is None, "教師預覽不得寫入 ET_PROGRESS（#255 裁示 Q1）"

    async def test_配分總和非一百時以百分比判定及格(self, client, db) -> None:
        """「配分總和 = 100」只在**發布當下**檢核，發布後教師仍可改。

        總和被改成 200 時，若直接拿 `total` 比 `PASS_SCORE`，答對一半（100 分）就會及格；
        改成 50 時則**任何人都不可能及格**——而測驗自本 issue 起是硬性解鎖門檻，那會讓
        整門課後半段對全班永久鎖死。
        """
        teacher = await _user(db, "t_att20", ROLE_TEACHER)
        student = await _user(db, "s_att20")
        course = await _course_with_quiz(client, db, teacher, code="32000020")
        q1 = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _add_question(client, teacher, course["quiz_id"], points=100)  # 總和 200
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        correct = next(o["option_id"] for o in q1["options"] if o["is_correct"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q1["question_id"]), json={"selected_options": [correct]}, headers=h
        )

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert float(r.json()["score"]) == 100.0
        assert r.json()["points_total"] == 200
        assert r.json()["is_pass"] is False, "100/200 = 50% < 80%，不應及格"


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


class TestReviewLastAttempt:
    """「查看上次作答明細」——提交後回頭複習的路徑。"""

    async def test_已提交的作答可再取回同一份成績(self, client, db) -> None:
        """明細取自 `_D.SCORE` / `_M.SCORE`，**不重算**。

        重算等於不信任閱卷結果；閱卷依當時快照算，事後任何改動都不該回頭影響它。
        """
        teacher = await _user(db, "t_att22", ROLE_TEACHER)
        student = await _user(db, "s_att22")
        course = await _course_with_quiz(client, db, teacher, code="32000022")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]),
            json={"selected_options": [q["options"][0]["option_id"]]},
            headers=h,
        )
        submitted = (await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)).json()
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] == submitted["score"]
        assert body["is_pass"] == submitted["is_pass"]
        assert body["points_total"] == submitted["points_total"]
        assert body["questions"] == submitted["questions"], "複習看到的明細與提交當下不一致"
        # 結果頁靠它導回學習頁——重考入口（測驗面板）在那裡，測驗已無獨立引導頁
        assert body["course_id"] == course["course_id"]
        assert submitted["course_id"] == course["course_id"]

    async def test_提交後教師改配分不影響回看的成績(self, client, db) -> None:
        """**「不重算」的破壞性測試**。

        只比對「剛提交」與「立刻回看」兩次是否一致，改成現算也會通過——中間沒人動題目，
        兩次數值本來就一樣。要驗的是提交**之後**題目被改，回看仍是提交當下的快照。
        """
        teacher = await _user(db, "t_att21", ROLE_TEACHER)
        student = await _user(db, "s_att21")
        course = await _course_with_quiz(client, db, teacher, code="32000021")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        # 提交後教師把配分砍半、題幹改掉、正確答案換成另一個選項
        flipped = [{**o, "is_correct": not o["is_correct"]} for o in q["options"]]
        await client.put(
            f"/api/et/questions/{q['question_id']}",
            json={"question_type": QUESTION_SINGLE, "stem": "改過的題幹", "points": 50, "options": flipped},
            headers=_bearer(teacher),
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert r.status_code == 200, r.text
        body = r.json()
        assert float(body["score"]) == 100.0, "重算會變 0（正確答案被換掉）"
        assert body["points_total"] == 100, "重算會變 50"
        assert body["questions"][0]["stem"] == "題幹", "題幹亦須為快照"
        assert body["questions"][0]["outcome"] == "CORRECT"

    async def test_進行中的作答沒有成績可看(self, client, db) -> None:
        """未提交 → 404，與「不存在」「非本人」共用同一回應，不讓差異變成存在性 oracle。"""
        teacher = await _user(db, "t_att23", ROLE_TEACHER)
        student = await _user(db, "s_att23")
        course = await _course_with_quiz(client, db, teacher, code="32000023")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_ATTEMPT_001"

    async def test_逾時自動提交的作答也看得到成績(self, client, db) -> None:
        """狀態白名單須含 `TIMEOUT`——逾時仍照常計分，成績當然也要看得到。

        只測 `SUBMITTED` 的話，白名單漏掉 `TIMEOUT` 會讓一整類學員的成績永遠 404。
        """
        teacher = await _user(db, "t_att26", ROLE_TEACHER)
        student = await _user(db, "s_att26")
        course = await _course_with_quiz(client, db, teacher, code="32000026")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        # 直接改狀態：真的等到逾時要等掉整個時限，而這裡要驗的是白名單不是計時
        await db.execute(
            update(EtQuizAttemptM)
            .where(EtQuizAttemptM.attempt_id == attempt["attempt_id"])
            .values(status=ATTEMPT_TIMEOUT)
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["status"] == ATTEMPT_TIMEOUT

    async def test_已軟刪除的作答取不到成績(self, client, db) -> None:
        """`DELETED = 1` 的 attempt 不得再回傳答案卷（教師刪項目會連帶軟刪）。"""
        teacher = await _user(db, "t_att27", ROLE_TEACHER)
        student = await _user(db, "s_att27")
        course = await _course_with_quiz(client, db, teacher, code="32000027")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        await db.execute(
            update(EtQuizAttemptM).where(EtQuizAttemptM.attempt_id == attempt["attempt_id"]).values(deleted=1)
        )
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert r.status_code == 404, r.text

    async def test_不可讀他人的成績明細(self, client, db) -> None:
        teacher = await _user(db, "t_att24", ROLE_TEACHER)
        owner = await _user(db, "s_att24a")
        other = await _user(db, "s_att24b")
        course = await _course_with_quiz(client, db, teacher, code="32000024")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, owner, course["course_id"])
        await _enroll(db, other, course["course_id"])
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(owner))).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=_bearer(owner))
        await db.commit()

        r = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=_bearer(other))

        assert r.status_code == 404, r.text

    async def test_次數用盡仍給得到上次作答的入口(self, client, db) -> None:
        """複習正是次數用完的學員最需要的——把入口跟著作答一起關掉等於懲罰他考不好。"""
        teacher = await _user(db, "t_att25", ROLE_TEACHER)
        student = await _user(db, "s_att25")
        course = await _course_with_quiz(client, db, teacher, code="32000025")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await client.put(
            f"/api/et/quizzes/{course['quiz_id']}",
            json={"quiz_name": "小考", "pass_score": 80, "time_limit_min": None, "max_retry": 0, "version": 0},
            headers=_bearer(teacher),
        )
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        before = await client.get(f"/api/et/quizzes/{course['quiz_id']}/intro", headers=h)
        assert before.json()["last_attempt_id"] is None, "尚未作答就給了複習入口"
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/intro", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["can_start"] is False, "MAX_RETRY=0 且已作答 1 次，應不可再作答"
        assert r.json()["last_attempt_id"] == attempt["attempt_id"]


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


class TestAttemptHistory:
    """ET-6b 歷次作答清單（#280 AC 1 / AC 3）。"""

    async def test_歷次清單列出全部次別(self, client, db) -> None:
        """AC 1：列出**每一次**，不限最近一次。"""
        teacher = await _user(db, "t_att28", ROLE_TEACHER)
        student = await _user(db, "s_att28")
        course = await _course_with_quiz(client, db, teacher, code="32000028")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        for _ in range(2):
            started = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
            await client.post(f"/api/et/attempts/{started['attempt_id']}/submit", headers=h)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)

        assert r.status_code == 200, r.text
        body = r.json()
        assert [a["attempt_no"] for a in body] == [1, 2], "須依 ATTEMPT_NO 遞增列出每一次"
        assert all(a["submitted_at"] is not None for a in body)
        assert {"attempt_id", "attempt_no", "submitted_at", "score", "is_pass", "status"} <= set(body[0])

    async def test_清單不含進行中的作答(self, client, db) -> None:
        """清單是「作答**紀錄**」；進行中的還沒有成績，列出來只會是一列空白。"""
        teacher = await _user(db, "t_att29", ROLE_TEACHER)
        student = await _user(db, "s_att29")
        course = await _course_with_quiz(client, db, teacher, code="32000029")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        first = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{first['attempt_id']}/submit", headers=h)
        # 第 2 次刻意不提交
        await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)

        assert [a["attempt_no"] for a in r.json()] == [1], "進行中的第 2 次不該入列"

    async def test_兩次作答各依自己的順序快照(self, client, db) -> None:
        """AC 3：不同 attempt **不互相污染**。

        ⚠️ 洗牌可能兩次剛好相同——那樣測不出污染。故直接改寫第 1 次的順序快照使其
        **確定**與第 2 次相反，再驗兩邊各自吻合自己的快照。
        """
        teacher = await _user(db, "t_att30", ROLE_TEACHER)
        student = await _user(db, "s_att30")
        course = await _course_with_quiz(client, db, teacher, code="32000030")
        for _ in range(3):
            await _add_question(client, teacher, course["quiz_id"], points=30)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        first = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{first['attempt_id']}/submit", headers=h)
        second = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{second['attempt_id']}/submit", headers=h)
        raw = await db.scalar(
            select(EtQuizAttemptM.question_order).where(EtQuizAttemptM.attempt_id == second["attempt_id"])
        )
        second_order = json.loads(raw)
        await db.execute(
            update(EtQuizAttemptM)
            .where(EtQuizAttemptM.attempt_id == first["attempt_id"])
            .values(question_order=json.dumps(list(reversed(second_order))))
        )
        await db.commit()

        first_result = await client.get(f"/api/et/attempts/{first['attempt_id']}/result", headers=h)
        second_result = await client.get(f"/api/et/attempts/{second['attempt_id']}/result", headers=h)

        assert [q["question_id"] for q in first_result.json()["questions"]] == list(reversed(second_order))
        assert [q["question_id"] for q in second_result.json()["questions"]] == second_order

    async def test_不可讀他人的歷次清單(self, client, db) -> None:
        teacher = await _user(db, "t_att31", ROLE_TEACHER)
        owner = await _user(db, "s_att31a")
        other = await _user(db, "s_att31b")
        course = await _course_with_quiz(client, db, teacher, code="32000031")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, owner, course["course_id"])
        await _enroll(db, other, course["course_id"])
        started = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(owner))).json()
        await client.post(f"/api/et/attempts/{started['attempt_id']}/submit", headers=_bearer(owner))
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=_bearer(other))

        assert r.status_code == 200, r.text
        assert r.json() == [], "只能看到自己的，不是別人的"


class TestClosedAndRemovedBoundaries:
    """ET-6b 課程關閉與被移除的邊界（#280 AC 6 / 7 / 8 / 9）。

    這四條的行為 **#279 已經實作**（`start()` 的續作分支先返回、`_require_own_attempt`
    只比對 `USER_ID`），但**沒有任何測試釘住**——本類別就是那些測試。
    """

    async def test_關閉後仍可提交進行中的作答(self, client, db) -> None:
        """AC 6 / `spec_us6` 場景 27：關閉當下已在作答者，沿用快照完成並計分。"""
        teacher = await _user(db, "t_att32", ROLE_TEACHER)
        student = await _user(db, "s_att32")
        course = await _course_with_quiz(client, db, teacher, code="32000032")
        q = await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        correct = next(o["option_id"] for o in q["options"] if o["is_correct"])
        await client.put(
            _answer_url(attempt["attempt_id"], q["question_id"]), json={"selected_options": [correct]}, headers=h
        )
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)

        assert r.status_code == 200, r.text
        assert float(r.json()["score"]) == 100.0, "關閉不影響閱卷"
        assert r.json()["status"] == ATTEMPT_SUBMITTED

    async def test_關閉後仍可讀歷次與明細(self, client, db) -> None:
        """AC 8：唯讀回看不受課程資格影響——用課程資格判定會讓學員連自己的歷史都讀不到。"""
        teacher = await _user(db, "t_att33", ROLE_TEACHER)
        student = await _user(db, "s_att33")
        course = await _course_with_quiz(client, db, teacher, code="32000033")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.commit()

        history = await client.get(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)
        detail = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=h)

        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert detail.status_code == 200, detail.text

    async def test_關閉時引導頁的原因是關閉而非次數用完(self, client, db) -> None:
        """`can_start` 的兩種成因對學員的意義完全不同。

        混為一句會叫課程關閉的學員去「聯繫教師重置」——而重置對他一點用也沒有。
        """
        teacher = await _user(db, "t_att34", ROLE_TEACHER)
        student = await _user(db, "s_att34")
        course = await _course_with_quiz(client, db, teacher, code="32000034")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.get(f"/api/et/quizzes/{course['quiz_id']}/intro", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["can_start"] is False
        assert r.json()["course_closed"] is True, "次數還有剩，不可作答的原因是課程關閉"

    async def test_被移除後仍可提交但不可開新(self, client, db) -> None:
        """AC 9 / `spec_us6` 場景 28：當前 attempt 完成並計入歷史，只有之後不能再開新的。

        提交當下就擋等於讓學員剛寫完的一份考卷憑空消失。
        """
        teacher = await _user(db, "t_att35", ROLE_TEACHER)
        student = await _user(db, "s_att35")
        course = await _course_with_quiz(client, db, teacher, code="32000035")
        await _add_question(client, teacher, course["quiz_id"], points=100)
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)
        attempt = (await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)).json()
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == course["course_id"])
            .values(is_removed=True)
        )
        await db.commit()

        submitted = await client.post(f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=h)
        history = await client.get(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=h)

        assert submitted.status_code == 200, submitted.text
        assert len(history.json()) == 1, "已完成的那次須計入歷史"

    async def test_被移除者看到的是被移除而非尚未加入(self, client, db) -> None:
        """AC 9 後半 / ET-MSG-ET06-006：next navigation 的訊息要說對原因。

        「您尚未加入此課程」會讓被移除的學員以為自己走錯課程、再去找一次邀請碼——
        而依 #247 裁示 C 他也不能自行加回，那是白費力氣。
        """
        teacher = await _user(db, "t_att36", ROLE_TEACHER)
        student = await _user(db, "s_att36")
        course = await _course_with_quiz(client, db, teacher, code="32000036")
        await _enroll(db, student, course["course_id"])
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == course["course_id"])
            .values(is_removed=True)
        )
        await db.commit()

        r = await client.get(f"/api/et/courses/{course['course_id']}/learn", headers=_bearer(student))

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_LEARN_004"
        assert r.json()["error_message"] == "您已被該課程移除"
