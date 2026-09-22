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

    async def test_空章節擋下發布並指出是哪一章(self, client, db) -> None:
        """#358 第 3 項。**必須在整合層驗**，unit 測不到的是那支彙總查詢。

        🔴 `_chapter_summaries` 用的是 `LEFT OUTER JOIN`——沒有項目的章節正是要抓的對象，
        INNER JOIN 會讓它們整個從結果消失、檢核永遠不觸發，而純函式的測試全綠。與
        `_quiz_summaries` 的 0 題測驗踩過同一個坑（見本檔檔頭第 1 點）。
        """
        uid = await _user(db, "t_pc_empty")
        cid = await _publishable_course(client, db, uid)
        empty = await client.post(
            f"{_COURSES}/{cid}/chapters", json={"chapter_name": "還沒放東西的一章"}, headers=_bearer(uid)
        )
        empty_id = empty.json()["chapter_id"]

        body = await _check(client, uid, cid)

        assert body["can_publish"] is False
        chapter_blockers = [b for b in body["blockers"] if b["code"] == "CHAPTER_EMPTY"]
        assert len(chapter_blockers) == 1
        assert chapter_blockers[0]["target_id"] == empty_id

    async def test_每章都有項目時不報空章節(self, client, db) -> None:
        """基準課程本來就每章有教材——少了這條，把檢核寫成恆真也會「通過」上一條。"""
        uid = await _user(db, "t_pc_nonempty")
        cid = await _publishable_course(client, db, uid)

        body = await _check(client, uid, cid)

        assert body["can_publish"] is True
        assert body["blockers"] == []

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


class TestUntitledItem:
    """#384：未命名的教材／測驗不得發布出去。

    ⚠️ 名稱**不在 `ET_ITEM` 上**——依 `ITEM_TYPE` 落在 `ET_MATERIAL.MATERIAL_NAME` 或
    `ET_QUIZ.QUIZ_NAME`。整合測試在這裡有價值：`_item_titles` 的兩個 outer join +
    `coalesce` 是純函式測不到的接線，接錯了 unit test 全綠而缺漏永遠不觸發
    （同 `_quiz_summaries` 與 `_chapter_summaries` 踩過的 INNER JOIN 坑）。
    """

    async def test_建立項目時名稱仍可留空(self, client, db) -> None:
        """🔴 AC 3：**不得為了修這個而推翻 2026-08-27 的裁示。**

        原本前端會代填「新教材」/「新測驗」，實測發現使用者開視窗第一件事就是把那串
        字選起來刪掉。修法只能加在**發布**這一關，不能把建立那關收緊——否則教師又會
        看到代填的字。這條測試就是釘住這件事，讓日後「順手補個 min_length」會變紅。
        """
        uid = await _user(db, "t_ut01")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "空名章"}, headers=_bearer(uid))

        created = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": ""},
            headers=_bearer(uid),
        )

        assert created.status_code == 201, created.text

    async def test_未命名教材擋下發布並指出是哪一個項目(self, client, db) -> None:
        uid = await _user(db, "t_ut02")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "空名章"}, headers=_bearer(uid))
        item = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": ""},
            headers=_bearer(uid),
        )

        body = await _check(client, uid, cid)

        assert body["can_publish"] is False
        assert ("ITEM_NO_TITLE", item.json()["item_id"]) in [(b["code"], b["target_id"]) for b in body["blockers"]]

    async def test_未命名測驗同樣被擋(self, client, db) -> None:
        """測驗側單獨驗一次——`coalesce` 取的是**另一張表**的欄位，教材通過不代表測驗也通過。"""
        uid = await _user(db, "t_ut03")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "空名測驗章"}, headers=_bearer(uid))
        item = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_QUIZ, "title": ""},
            headers=_bearer(uid),
        )

        body = await _check(client, uid, cid)

        codes = [(b["code"], b["target_id"]) for b in body["blockers"]]
        assert ("ITEM_NO_TITLE", item.json()["item_id"]) in codes

    async def test_補上名稱後該缺漏消失(self, client, db) -> None:
        """釘住「修好就放行」——只驗擋得住，驗不出它是不是永遠擋著。"""
        uid = await _user(db, "t_ut04")
        cid = await _publishable_course(client, db, uid)
        ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "空名章"}, headers=_bearer(uid))
        item = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": ""},
            headers=_bearer(uid),
        )
        material_id = item.json()["material_id"]
        before = await _check(client, uid, cid)
        assert any(b["code"] == "ITEM_NO_TITLE" for b in before["blockers"])

        saved = await client.put(
            f"/api/et/materials/{material_id}",
            # `description_html` 不可省：教材儲存另有「至少提供影片、文件或說明文字其中
            # 一項」之檢核（`ET_MATERIAL_002`），少了它會 422 而非 200。
            json={
                "material_name": "補上的名稱",
                "description_html": "<p>內容</p>",
                "doc_ids": [],
                "video_ids": [],
                "version": 0,
            },
            headers=_bearer(uid),
        )
        assert saved.status_code == 204, saved.text

        after = await _check(client, uid, cid)
        assert not any(b["code"] == "ITEM_NO_TITLE" for b in after["blockers"])
        assert after["can_publish"] is True


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
