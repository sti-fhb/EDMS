"""ET02 課程發布整合測試（US3 / #204）。

六項檢核的**組合邏輯**已由 `tests/unit/et/test_publish_rules.py` 以純函式涵蓋。
這裡只驗需要真 DB 才驗得了的事：

1. `EtPublishRepository` 的彙總查詢是否真的問對了東西——特別是 **0 題的測驗必須
   出現在結果裡**（用 INNER JOIN 會讓它整個消失，檢核就永遠不觸發）
2. 發布之寫入：狀態、首次發布時間、邀請碼三者
3. `ET_PUBLISH_001` 之 `blockers` 是否真的出現在回應 body（`AppError.extra` 的接線）
4. 狀態機：非草稿不可發布
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_TEACHER,
    SURVEY_QUESTION_SINGLE,
)
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


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


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _tag(db, name: str) -> int:
    now = utcnow()
    tag = EtTag(tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=now, deleted=0)
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _attach_tag(db, course_id: int, tag_id: int) -> None:
    db.add(EtCourseTag(course_id=course_id, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()


async def _publishable_course(client, db, uid: str, *, with_quiz: bool = False) -> int:
    """建一門**恰好滿足全部檢核**的課程：1 章節 + 1 教材 + 1 標籤 + 起訖時間。

    各測試只弄壞想驗的那一項，失敗原因才不會是基準資料本身有第二個問題。
    """
    created = await client.post(
        _COURSES,
        json={
            "course_name": "可發布課程",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2026-09-30T00:00:00Z",
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    # 標籤名以 course_id 命名——`UQ_ET_TAG_NAME` 為全域唯一，用 uid 命名會讓
    # 「同一位教師建多門課」的測試（如邀請碼不重複）在第二門課就撞名。
    await _attach_tag(db, cid, await _tag(db, f"標籤{cid}"))

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    chapter_id = ch.json()["chapter_id"]
    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(uid),
    )
    assert mat.status_code == 201, mat.text

    if with_quiz:
        quiz = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_QUIZ, "title": "小考"},
            headers=_bearer(uid),
        )
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
    return cid


async def _check(client, uid: str, course_id: int) -> dict:
    r = await client.get(f"{_COURSES}/{course_id}/publish-check", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    return r.json()


class TestPublishCheck:
    async def test_全部滿足時可發布(self, client, db) -> None:
        uid = await _user(db, "t_pc01")
        cid = await _publishable_course(client, db, uid)
        body = await _check(client, uid, cid)
        assert body["can_publish"] is True
        assert body["blockers"] == []

    async def test_未建立問卷不阻擋(self, client, db) -> None:
        """AC 23：問卷為選配。基準課程本來就沒有問卷，能通過即證明這條。"""
        uid = await _user(db, "t_pc02")
        cid = await _publishable_course(client, db, uid)
        assert (await _check(client, uid, cid))["can_publish"] is True

    async def test_無標籤與無時間之缺漏(self, client, db) -> None:
        uid = await _user(db, "t_pc03")
        created = await client.post(_COURSES, json={"course_name": "空課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        body = await _check(client, uid, cid)
        assert body["can_publish"] is False
        assert {b["code"] for b in body["blockers"]} == {"NO_CHAPTER", "NO_MATERIAL", "NO_TAG", "NO_SCHEDULE"}

    async def test_零題測驗被抓到(self, client, db) -> None:
        """**第六項檢核**（SA 裁示 Q3）與 `_quiz_summaries` 之 LEFT JOIN 的關鍵測試。

        空殼測驗沒有任何 `ET_QUESTION` 列；若彙總查詢用 INNER JOIN，這個測驗會整個
        不出現在結果裡，檢核就永遠不會觸發——而課程照常發布出去，學員點進去看到一份
        沒有題目的考卷。
        """
        uid = await _user(db, "t_pc04")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "測驗章"}, headers=_bearer(uid))
        quiz = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_QUIZ, "title": "空測驗"},
            headers=_bearer(uid),
        )
        body = await _check(client, uid, cid)
        assert body["can_publish"] is False
        assert [(b["code"], b["target_id"]) for b in body["blockers"]] == [("QUIZ_NO_QUESTION", quiz.json()["quiz_id"])]

    async def test_配分不足一百被抓到(self, client, db) -> None:
        uid = await _user(db, "t_pc05")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "測驗章"}, headers=_bearer(uid))
        quiz = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_QUIZ, "title": "配分不足"},
            headers=_bearer(uid),
        )
        quiz_id = quiz.json()["quiz_id"]
        await client.post(
            f"/api/et/quizzes/{quiz_id}/questions",
            json={
                "question_type": QUESTION_SINGLE,
                "stem": "題幹",
                "points": 60,
                "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
            },
            headers=_bearer(uid),
        )
        body = await _check(client, uid, cid)
        assert [(b["code"], b["target_id"]) for b in body["blockers"]] == [("QUIZ_POINTS", quiz_id)]

    async def test_配分剛好一百可發布(self, client, db) -> None:
        uid = await _user(db, "t_pc06")
        cid = await _publishable_course(client, db, uid, with_quiz=True)
        assert (await _check(client, uid, cid))["can_publish"] is True

    async def test_已刪除的章節不計入(self, client, db) -> None:
        """彙總查詢須排除 `DELETED = 1`——否則刪掉全部章節後仍以為課程有內容。"""
        uid = await _user(db, "t_pc07")
        cid = await _publishable_course(client, db, uid)
        detail = (await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))).json()
        for chapter in detail["chapters"]:
            await client.delete(f"/api/et/chapters/{chapter['chapter_id']}", headers=_bearer(uid))

        body = await _check(client, uid, cid)
        assert {b["code"] for b in body["blockers"]} == {"NO_CHAPTER", "NO_MATERIAL"}

    async def test_有問卷但零題被擋(self, client, db) -> None:
        """第七項檢核（2026-08-28 實測回饋）。走真實路徑：建問卷但不加題目。

        `_survey_question_count` 對「沒有問卷」回 None、「有問卷 0 題」回 0——
        這條驗的是後者確實被擋，`test_未建立問卷不阻擋` 驗前者不被擋。
        """
        uid = await _user(db, "t_pc10")
        cid = await _publishable_course(client, db, uid)
        created = await client.post(
            f"{_COURSES}/{cid}/survey", json={"survey_name": "space survey"}, headers=_bearer(uid)
        )
        assert created.status_code == 201, created.text

        body = await _check(client, uid, cid)
        assert body["can_publish"] is False
        assert [(b["code"], b["target_id"]) for b in body["blockers"]] == [("SURVEY_NO_QUESTION", None)]

    async def test_有問卷且有題目可發布(self, client, db) -> None:
        uid = await _user(db, "t_pc11")
        cid = await _publishable_course(client, db, uid)
        created = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "ok survey"}, headers=_bearer(uid))
        await client.post(
            f"/api/et/surveys/{created.json()['survey_id']}/questions",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "stem",
                "options": [{"option_text": "A"}, {"option_text": "B"}],
            },
            headers=_bearer(uid),
        )
        assert (await _check(client, uid, cid))["can_publish"] is True

    async def test_非擁有者不可預檢(self, client, db) -> None:
        owner = await _user(db, "t_pc08")
        other = await _user(db, "t_pc09")
        cid = await _publishable_course(client, db, owner)
        r = await client.get(f"{_COURSES}/{cid}/publish-check", headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestPublish:
    async def test_發布成功寫入三者(self, client, db) -> None:
        """AC 24：狀態、首次發布時間、8 碼邀請碼。"""
        uid = await _user(db, "t_pb01")
        cid = await _publishable_course(client, db, uid, with_quiz=True)
        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == COURSE_PUBLISHED
        assert len(body["invitation_code"]) == 8
        assert body["invitation_code"].isdigit()

        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        await db.refresh(course)
        assert course.status == COURSE_PUBLISHED
        assert course.first_published_at is not None
        assert course.invitation_code == body["invitation_code"]

    async def test_邀請碼不重複(self, client, db) -> None:
        """`UQ_ET_COURSE_INVITATION_CODE` 為全域唯一；產碼須避開既有碼。"""
        uid = await _user(db, "t_pb02")
        codes = set()
        for _ in range(3):
            cid = await _publishable_course(client, db, uid, with_quiz=True)
            r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
            assert r.status_code == 200, r.text
            codes.add(r.json()["invitation_code"])
        assert len(codes) == 3

    async def test_檢核未通過帶缺漏清單(self, client, db) -> None:
        """AC 26 / ET-MSG-ET02-011：錯誤 body 須含**具體缺漏項目**。

        這條同時驗 `AppError.extra` 的接線——沒接上的話 body 只會有
        `error_code` / `error_message` 兩個欄位，前端就只能顯示「發布條件未滿足」，
        教師得自己猜是哪裡不合格。
        """
        uid = await _user(db, "t_pb03")
        created = await client.post(_COURSES, json={"course_name": "空課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]

        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
        assert r.status_code == 422
        body = r.json()
        assert body["error_code"] == "ET_PUBLISH_001"
        assert {b["code"] for b in body["blockers"]} == {"NO_CHAPTER", "NO_MATERIAL", "NO_TAG", "NO_SCHEDULE"}
        # 標準欄位未被 extra 蓋掉
        assert body["error_message"] == "發布條件未滿足"

    async def test_檢核未通過不改變狀態(self, client, db) -> None:
        uid = await _user(db, "t_pb04")
        created = await client.post(_COURSES, json={"course_name": "空課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))

        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        await db.refresh(course)
        assert course.status == "DRAFT"
        assert course.invitation_code is None

    async def test_已發布課程不可再發布(self, client, db) -> None:
        """AC 28：已發布課程的編輯**即時生效、不需重新發布**，故此端點不是再發布的入口。"""
        uid = await _user(db, "t_pb05")
        cid = await _publishable_course(client, db, uid, with_quiz=True)
        await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))

        again = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
        assert again.status_code == 409
        assert again.json()["error_code"] == "ET_PUBLISH_002"

    async def test_非擁有者不可發布(self, client, db) -> None:
        owner = await _user(db, "t_pb06")
        other = await _user(db, "t_pb07")
        cid = await _publishable_course(client, db, owner, with_quiz=True)
        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_發布後仍可編輯(self, client, db) -> None:
        """AC 28：已發布課程繼續編輯、儲存即時生效。"""
        uid = await _user(db, "t_pb08")
        cid = await _publishable_course(client, db, uid, with_quiz=True)
        await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))

        detail = (await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))).json()
        r = await client.put(
            f"{_COURSES}/{cid}",
            json={
                "course_name": "改過的名稱",
                "description": None,
                "open_start_at": detail["open_start_at"],
                "open_end_at": detail["open_end_at"],
                "require_approval": False,
                "tag_ids": detail["tag_ids"],
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        after = (await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))).json()
        assert after["course_name"] == "改過的名稱"
        assert after["status"] == COURSE_PUBLISHED
