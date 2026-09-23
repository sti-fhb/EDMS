"""ET05 測驗未及格阻擋解鎖（`spec_us5` AC 12 / #361 AC 7、8）。

解鎖判定本身是純函式，已於 `tests/unit/et/test_progress_rules.py` 驗完。此處只驗
**需要真 DB 與真端點才驗得了**的三件事：

1. **側欄旗標與後端守門給出同一個答案**——issue 特別點名的風險。兩邊各算一份時，
   分岔的表現是「側欄顯示解鎖但後端擋下」，一個學員完全無法理解的狀態，而純函式
   測試永遠抓不到（它們餵的是同一個輸入）。
2. **ET03 重置逃生門實際走得通**（AC 8）——這是 AC 12 得以啟用的唯一前提。#279 當年
   不啟用的理由就是「沒有任何補救途徑」，而該途徑從未被端到端走過一次。
3. **0 題的測驗不當閘門**——重置救不了的那種死路，見 `build_item_state` 之 docstring。
"""

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
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


async def _add_question(client, teacher: str, quiz_id: int) -> dict:
    r = await client.post(
        f"/api/et/quizzes/{quiz_id}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "題幹",
            "points": 100,
            "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
        },
        headers=_bearer(teacher),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _course(client, db, teacher: str, *, code: str) -> dict:
    """第 1 章 = [測驗甲, 測驗乙]、第 2 章 = [教材]，各測驗一題，發布並開放。

    ⭐ **後續項目刻意也是測驗**：如此「後端守門」可用「開始作答」端點驗到（該端點會
    呼叫 `is_item_locked`），與側欄旗標對照才有意義。若後續項目是教材，就只驗得到
    側欄那一半。
    """
    created = await client.post(_COURSES, json={"course_name": "採血作業教育"}, headers=_bearer(teacher))
    course_id = created.json()["course_id"]
    ch1 = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
    )
    first = await client.post(
        f"/api/et/chapters/{ch1.json()['chapter_id']}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考甲"},
        headers=_bearer(teacher),
    )
    second = await client.post(
        f"/api/et/chapters/{ch1.json()['chapter_id']}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考乙"},
        headers=_bearer(teacher),
    )
    ch2 = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(teacher)
    )
    third = await client.post(
        f"/api/et/chapters/{ch2.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL},
        headers=_bearer(teacher),
    )
    result = {
        "course_id": course_id,
        "first_item_id": first.json()["item_id"],
        "first_quiz_id": first.json()["quiz_id"],
        "second_item_id": second.json()["item_id"],
        "second_quiz_id": second.json()["quiz_id"],
        "next_chapter_item_id": third.json()["item_id"],
    }
    result["first_question"] = await _add_question(client, teacher, result["first_quiz_id"])
    await _add_question(client, teacher, result["second_quiz_id"])
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(status=COURSE_PUBLISHED, invitation_code=code, open_start_at=utcnow() - timedelta(hours=1))
    )
    await db.flush()
    return result


async def _learn(client, user_id: str, course_id: int) -> dict:
    r = await client.get(f"{_COURSES}/{course_id}/learn", headers=_bearer(user_id))
    assert r.status_code == 200, r.text
    return r.json()


async def _sidebar(client, student: str, course_id: int) -> dict[int, dict]:
    body = await _learn(client, student, course_id)
    return {i["item_id"]: i for c in body["chapters"] for i in c["items"]}


async def _attempt_quiz(client, student: str, quiz_id: int, *, correct: bool, question: dict) -> dict:
    """完整作答一次並提交。`correct=False` 時選錯答案。"""
    h = _bearer(student)
    started = await client.post(f"/api/et/quizzes/{quiz_id}/attempts", headers=h)
    assert started.status_code in (200, 201), started.text
    attempt_id = started.json()["attempt_id"]
    option = next(o["option_id"] for o in question["options"] if o["is_correct"] is correct)
    await client.put(
        f"/api/et/attempts/{attempt_id}/answers/{question['question_id']}",
        json={"selected_options": [option]},
        headers=h,
    )
    submitted = await client.post(f"/api/et/attempts/{attempt_id}/submit", headers=h)
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


async def _set_max_retry(client, teacher: str, quiz_id: int, max_retry: int) -> None:
    current = await client.get(f"/api/et/quizzes/{quiz_id}", headers=_bearer(teacher))
    assert current.status_code == 200, current.text
    quiz = current.json()
    r = await client.put(
        f"/api/et/quizzes/{quiz_id}",
        json={
            "quiz_name": quiz["quiz_name"],
            "pass_score": quiz["pass_score"],
            "max_retry": max_retry,
            "version": quiz["version"],
        },
        headers=_bearer(teacher),
    )
    assert r.status_code == 204, r.text


class TestQuizBlocksUnlock:
    """AC 7：測驗未及格阻擋解鎖。"""

    async def test_未及格則同章後續項目與下一章皆鎖定(self, client, db) -> None:
        """AC 12 的本體。2026-09-22 之前這三項全部是解鎖的（測驗恆視為通過）。"""
        teacher = await _user(db, "t_gate01", ROLE_TEACHER)
        student = await _user(db, "s_gate01")
        course = await _course(client, db, teacher, code="33000001")
        await _enroll(db, student, course["course_id"])

        result = await _attempt_quiz(
            client, student, course["first_quiz_id"], correct=False, question=course["first_question"]
        )

        assert result["is_pass"] is False
        items = await _sidebar(client, student, course["course_id"])
        assert items[course["first_item_id"]]["locked"] is False, "測驗自己是第一項，恆解鎖"
        assert items[course["second_item_id"]]["locked"] is True, "未及格必須擋住同章後續"
        assert items[course["next_chapter_item_id"]]["locked"] is True, "未及格必須擋住下一章"

    async def test_側欄旗標與後端守門一致(self, client, db) -> None:
        """🔴 issue 特別點名的風險：兩邊各算一份會「側欄解鎖但後端擋下」。

        純函式測試抓不到這件事——它們餵的是同一個輸入。只有真的打兩個端點才驗得到。
        """
        teacher = await _user(db, "t_gate02", ROLE_TEACHER)
        student = await _user(db, "s_gate02")
        course = await _course(client, db, teacher, code="33000002")
        await _enroll(db, student, course["course_id"])
        await _attempt_quiz(client, student, course["first_quiz_id"], correct=False, question=course["first_question"])

        items = await _sidebar(client, student, course["course_id"])
        blocked = await client.post(f"/api/et/quizzes/{course['second_quiz_id']}/attempts", headers=_bearer(student))

        assert items[course["second_item_id"]]["locked"] is True, "側欄說鎖定"
        # 鎖定中的項目視同不存在 → 404（不讓回應差異變成「這個 id 存在」的 oracle）
        assert blocked.status_code == 404, blocked.text
        assert blocked.json()["error_code"] == "ET_ATTEMPT_001"

    async def test_及格後解鎖後續(self, client, db) -> None:
        """反向：AC 12 擋的只有未及格者，及格就該通。"""
        teacher = await _user(db, "t_gate03", ROLE_TEACHER)
        student = await _user(db, "s_gate03")
        course = await _course(client, db, teacher, code="33000003")
        await _enroll(db, student, course["course_id"])

        result = await _attempt_quiz(
            client, student, course["first_quiz_id"], correct=True, question=course["first_question"]
        )

        assert result["is_pass"] is True
        items = await _sidebar(client, student, course["course_id"])
        assert items[course["second_item_id"]]["locked"] is False
        allowed = await client.post(f"/api/et/quizzes/{course['second_quiz_id']}/attempts", headers=_bearer(student))
        assert allowed.status_code == 201, allowed.text

    async def test_未作答亦擋住後續(self, client, db) -> None:
        """沒考過與考不過同樣是「未完成」——不能只擋考壞的人。"""
        teacher = await _user(db, "t_gate04", ROLE_TEACHER)
        student = await _user(db, "s_gate04")
        course = await _course(client, db, teacher, code="33000004")
        await _enroll(db, student, course["course_id"])

        items = await _sidebar(client, student, course["course_id"])

        assert items[course["second_item_id"]]["locked"] is True
        assert items[course["next_chapter_item_id"]]["locked"] is True


class TestZeroQuestionQuizDoesNotGate:
    """0 題的測驗不當閘門——重置救不了的那種死路。"""

    async def test_題目被刪光的測驗不擋住後續(self, client, db) -> None:
        """走真實路徑：發布後教師把唯一一題刪掉（`delete_question` 不擋最後一題）。

        此時學員**連考都考不了**（`attempt/service` 對 0 題測驗回 404），ET03 也不會
        給重置鈕（`can_reset_retry` 要求 `used > max_retry`，而他一次都用不掉）。
        擋住它等於整門課後半段永久鎖死且無從補救。
        """
        teacher = await _user(db, "t_gate05", ROLE_TEACHER)
        student = await _user(db, "s_gate05")
        course = await _course(client, db, teacher, code="33000005")
        await _enroll(db, student, course["course_id"])

        deleted = await client.delete(
            f"/api/et/questions/{course['first_question']['question_id']}", headers=_bearer(teacher)
        )

        assert deleted.status_code == 204, deleted.text
        items = await _sidebar(client, student, course["course_id"])
        assert items[course["second_item_id"]]["locked"] is False, "0 題測驗不得擋住同章後續"
        # 後端守門必須同意——這正是側欄與守門分岔最可能出現的地方
        allowed = await client.post(f"/api/et/quizzes/{course['second_quiz_id']}/attempts", headers=_bearer(student))
        assert allowed.status_code == 201, allowed.text

    async def test_零題測驗自己仍未完成且仍擋住下一章(self, client, db) -> None:
        """不當閘門 ≠ 算他通過。

        側欄仍不打勾（他確實沒通過），而**同章還有一份有題目的測驗乙未通過**，故下一章
        照樣鎖著——「0 題不擋」放行的只有它自己那一格。
        """
        teacher = await _user(db, "t_gate06", ROLE_TEACHER)
        student = await _user(db, "s_gate06")
        course = await _course(client, db, teacher, code="33000006")
        await _enroll(db, student, course["course_id"])
        await client.delete(f"/api/et/questions/{course['first_question']['question_id']}", headers=_bearer(teacher))

        items = await _sidebar(client, student, course["course_id"])

        assert items[course["first_item_id"]]["completed"] is False, "側欄不得打勾"
        assert items[course["next_chapter_item_id"]]["locked"] is True

    async def test_教材項目不因無題目而繞過解鎖判定(self, client, db) -> None:
        """🔴 回歸測試：教材的 `QUIZ_ID` 為 NULL，題數子查詢對它也會得到 0。

        查詢少了 `QUIZ_ID IS NOT NULL` 的話，**每一個教材項目都會被當成零題測驗**而
        整批繞過解鎖判定——AC 12 會看起來有啟用（測驗那格擋得住），實際上所有教材
        都不再擋路。這條會紅，而純函式測試永遠不會。
        """
        teacher = await _user(db, "t_gate07", ROLE_TEACHER)
        student = await _user(db, "s_gate07")
        created = await client.post(_COURSES, json={"course_name": "教材順序"}, headers=_bearer(teacher))
        course_id = created.json()["course_id"]
        ch = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
        )
        items_created = [
            (
                await client.post(
                    f"/api/et/chapters/{ch.json()['chapter_id']}/items",
                    json={"item_type": ITEM_MATERIAL},
                    headers=_bearer(teacher),
                )
            ).json()["item_id"]
            for _ in range(2)
        ]
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id)
            .values(status=COURSE_PUBLISHED, invitation_code="33000007", open_start_at=utcnow() - timedelta(hours=1))
        )
        await _enroll(db, student, course_id)
        await db.flush()

        items = await _sidebar(client, student, course_id)

        assert items[items_created[0]]["locked"] is False, "第一項恆解鎖"
        assert items[items_created[1]]["locked"] is True, "未完成第一份教材就不該解鎖第二份"


class TestBlockingItemType:
    """`spec_us5` AC 12 的後半：阻擋**並提示**（ET-MSG-ET05-002）。

    🔴 前端原本對任何鎖定項目都提示「請先完成本章節之影片學習」。AC 12 啟用前那句
    永遠是對的（鎖定的唯一成因就是教材沒看完），啟用後會**把考不過的學員指向錯的
    動作**——叫他去看早就看完的影片。故後端要說出前緣是哪一型。
    """

    async def test_前緣是測驗時回_QUIZ(self, client, db) -> None:
        teacher = await _user(db, "t_gate10", ROLE_TEACHER)
        student = await _user(db, "s_gate10")
        course = await _course(client, db, teacher, code="33000010")
        await _enroll(db, student, course["course_id"])
        await _attempt_quiz(client, student, course["first_quiz_id"], correct=False, question=course["first_question"])

        body = await _learn(client, student, course["course_id"])

        assert body["blocking_item_type"] == ITEM_QUIZ

    async def test_前緣是教材時回_MATERIAL(self, client, db) -> None:
        """同一門課只換前緣的型別——確認它真的跟著前緣走，不是寫死。"""
        teacher = await _user(db, "t_gate11", ROLE_TEACHER)
        student = await _user(db, "s_gate11")
        created = await client.post(_COURSES, json={"course_name": "教材在前"}, headers=_bearer(teacher))
        course_id = created.json()["course_id"]
        ch = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
        )
        await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL},
            headers=_bearer(teacher),
        )
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id)
            .values(status=COURSE_PUBLISHED, invitation_code="33000011", open_start_at=utcnow() - timedelta(hours=1))
        )
        await _enroll(db, student, course_id)
        await db.flush()

        body = await _learn(client, student, course_id)

        assert body["blocking_item_type"] == ITEM_MATERIAL

    async def test_教師預覽恆為_None(self, client, db) -> None:
        """教師不累積進度、也不套用鎖定，故沒有「前緣」可言。

        ⚠️ 若照學員規則算，會對著自己的課提示「請先完成…」——而他根本不在學。
        """
        teacher = await _user(db, "t_gate12", ROLE_TEACHER)
        course = await _course(client, db, teacher, code="33000012")

        body = await _learn(client, teacher, course["course_id"])

        assert body["is_owner"] is True
        assert body["blocking_item_type"] is None


class TestResetEscapeHatch:
    """AC 8：次數用盡且未及格者，教師可由 ET03 重置後續行。

    🔴 **這是 AC 12 得以啟用的前提**。#279 當年不啟用的唯一理由就是「沒有任何補救
    途徑」，而 ET-9（#329）交付重置後，這條路徑從未被端到端走過一次。
    """

    async def test_次數用盡未及格者經教師重置後可續行(self, client, db) -> None:
        """完整來回：考壞 → 被擋且無次數 → 教師重置 → 再考及格 → 解鎖。"""
        teacher = await _user(db, "t_gate08", ROLE_TEACHER)
        student = await _user(db, "s_gate08")
        course = await _course(client, db, teacher, code="33000008")
        # `max_retry=0` 即「不允許重考」——一次考壞就用盡，不必打四次
        await _set_max_retry(client, teacher, course["first_quiz_id"], 0)
        await _enroll(db, student, course["course_id"])
        await _attempt_quiz(client, student, course["first_quiz_id"], correct=False, question=course["first_question"])

        # ① 次數用盡：連重考都開不起來
        exhausted = await client.post(f"/api/et/quizzes/{course['first_quiz_id']}/attempts", headers=_bearer(student))
        assert exhausted.status_code == 409, exhausted.text
        assert exhausted.json()["error_code"] == "ET_ATTEMPT_002"
        # ② 且後續被鎖死——這就是 #279 當年擔心的狀態
        items = await _sidebar(client, student, course["course_id"])
        assert items[course["second_item_id"]]["locked"] is True

        # ③ 教師由 ET03 重置
        reset = await client.post(
            f"{_COURSES}/{course['course_id']}/students/{student}/quizzes/{course['first_quiz_id']}/retry-reset",
            headers=_bearer(teacher),
        )
        assert reset.status_code == 200, reset.text

        # ④ 逃生門真的通：可再考，且及格後解鎖
        again = await _attempt_quiz(
            client, student, course["first_quiz_id"], correct=True, question=course["first_question"]
        )
        assert again["is_pass"] is True
        items = await _sidebar(client, student, course["course_id"])
        assert items[course["first_item_id"]]["completed"] is True
        assert items[course["second_item_id"]]["locked"] is False, "重置 → 及格 → 解鎖，逃生門完整"

    async def test_重置不刪除任何歷次作答(self, client, db) -> None:
        """逃生門不得以毀掉歷史為代價（US9 AC 6 / #279 Q2=C）。

        重置後 `attempt_no` 由 2 起算——次數歸 0 是靠 `ET_QUIZ_RETRY_RESET` 記基準，
        不是把第 1 次刪掉。
        """
        teacher = await _user(db, "t_gate09", ROLE_TEACHER)
        student = await _user(db, "s_gate09")
        course = await _course(client, db, teacher, code="33000009")
        await _set_max_retry(client, teacher, course["first_quiz_id"], 0)
        await _enroll(db, student, course["course_id"])
        await _attempt_quiz(client, student, course["first_quiz_id"], correct=False, question=course["first_question"])
        await client.post(
            f"{_COURSES}/{course['course_id']}/students/{student}/quizzes/{course['first_quiz_id']}/retry-reset",
            headers=_bearer(teacher),
        )

        second = await client.post(f"/api/et/quizzes/{course['first_quiz_id']}/attempts", headers=_bearer(student))

        assert second.status_code == 201, second.text
        assert second.json()["attempt_no"] == 2, "第 1 次仍在，故新的一次是第 2 次"
