"""ET02 課後問卷整合測試（US3 / #204）。

重點在需要真 DB 才驗得了的事：

1. **一門課程 0～1 份**——靠 `UQ_ET_SURVEY_COURSE` 與應用層雙重把關
2. **凍結**——須先建 `ET_SURVEY_RESPONSE_M` 測資才驗得出，且要驗「停用仍可」
3. **選項全量覆寫**——舊列軟刪後新列自 1 起插入，會撞上 `UX_ET_SURVEY_OPTION_ORDER`
   若它不是部分索引（migration `e9ec96adabab`）
4. **題目重排之兩階段寫入**——交換相鄰兩題必然經過順序重複的中間狀態
5. 樂觀鎖粒度：題目重排帶問卷層 version，不動題目自身 version
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ROLE_TEACHER,
    SURVEY_QUESTION_SINGLE,
    SURVEY_QUESTION_TEXT,
)
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole
from app.et.survey.models import EtSurveyOption, EtSurveyQuestion, EtSurveyResponseM

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


async def _course(client, uid: str) -> int:
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    assert created.status_code == 201, created.text
    return created.json()["course_id"]


async def _survey(client, uid: str, course_id: int, name: str = "課後滿意度問卷") -> dict:
    r = await client.post(f"{_COURSES}/{course_id}/survey", json={"survey_name": name}, headers=_bearer(uid))
    assert r.status_code == 201, r.text
    return r.json()


_DEFAULT_OPTIONS = [{"option_text": "滿意"}, {"option_text": "普通"}, {"option_text": "不滿意"}]


def _question_body(*, qtype=SURVEY_QUESTION_SINGLE, stem="您對本課程是否滿意？", options=None) -> dict:
    """組題目請求。

    ⚠️ 以 `is None` 判斷而非 `options or 預設`——**空陣列是 falsy**，用 `or` 會讓
    「明確傳入 0 個選項」被預設值吃掉，那條測試就變成假綠（測到的是 3 個選項）。
    比照 `test_et_quiz.py` 之同型修正。
    """
    return {
        "question_type": qtype,
        "stem": stem,
        "options": _DEFAULT_OPTIONS if options is None else options,
    }


async def _add_question(client, uid: str, survey_id: int, **kwargs) -> dict:
    r = await client.post(f"/api/et/surveys/{survey_id}/questions", json=_question_body(**kwargs), headers=_bearer(uid))
    assert r.status_code == 201, r.text
    return r.json()


async def _respond(db, survey_id: int, user_id: str = "student01") -> None:
    """建一筆填答主檔——凍結判定的觸發條件。"""
    db.add(
        EtSurveyResponseM(
            survey_id=survey_id,
            user_id=user_id,
            submitted_at=utcnow(),
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


class TestSurveyLifecycle:
    async def test_建立問卷(self, client, db) -> None:
        uid = await _user(db, "t_srv01")
        cid = await _course(client, uid)
        body = await _survey(client, uid, cid)
        assert body["survey_name"] == "課後滿意度問卷"
        assert body["is_active"] is True
        assert body["frozen"] is False
        assert body["questions"] == []

    async def test_重複建立被擋(self, client, db) -> None:
        """AC 22 / ET-MSG-ET02-010：一門課程 0～1 份。"""
        uid = await _user(db, "t_srv02")
        cid = await _course(client, uid)
        await _survey(client, uid, cid)
        again = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "第二份"}, headers=_bearer(uid))
        assert again.status_code == 409
        assert again.json()["error_code"] == "ET_SURVEY_002"

    async def test_未建立問卷回_null_而非_404(self, client, db) -> None:
        """AC 23：問卷為選配，「沒有」是正常狀態。

        回 404 會被前端錯誤處理當成故障顯示，讓每個沒建問卷的課程都跳一次錯誤。
        """
        uid = await _user(db, "t_srv03")
        cid = await _course(client, uid)
        r = await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))
        assert r.status_code == 200
        assert r.json() is None

    async def test_停用問卷(self, client, db) -> None:
        uid = await _user(db, "t_srv04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}",
            json={"survey_name": survey["survey_name"], "is_active": False, "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        after = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert after["is_active"] is False
        assert after["version"] == survey["version"] + 1

    async def test_非擁有者不可建立(self, client, db) -> None:
        owner = await _user(db, "t_srv05")
        other = await _user(db, "t_srv06")
        cid = await _course(client, owner)
        r = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "偷建"}, headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_草稿課程可刪除問卷(self, client, db) -> None:
        """#238 推翻 #204 之裁示 Q1：未發布課程可刪除問卷。"""
        uid = await _user(db, "t_srv07")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.delete(f"/api/et/surveys/{survey['survey_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text
        assert (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json() is None


class TestSurveyQuestions:
    async def test_新增題目與選項(self, client, db) -> None:
        uid = await _user(db, "t_sq01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        assert row["sort_order"] == 1
        assert [o["option_text"] for o in row["options"]] == ["滿意", "普通", "不滿意"]
        assert [o["sort_order"] for o in row["options"]] == [1, 2, 3]

    async def test_選項不足兩個被擋(self, client, db) -> None:
        """AC 19 / ET-MSG-ET02-008。"""
        uid = await _user(db, "t_sq02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(options=[{"option_text": "只有一個"}]),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_004"

    async def test_零個選項被擋(self, client, db) -> None:
        """`options=[]` 明確傳入空陣列——`_question_body` 以 `is None` 判斷，
        這裡送的確實是 0 個選項而非預設的 3 個。
        """
        uid = await _user(db, "t_sq03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(options=[]),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_004"

    async def test_更新題目選項全量覆寫(self, client, db) -> None:
        """舊選項軟刪、新選項自 `SORT_ORDER=1` 起插入。

        若 `UX_ET_SURVEY_OPTION_ORDER` 不是**部分**唯一索引，舊列會繼續佔著 1，
        第一個新選項就插不進去——本測試即為 migration `e9ec96adabab` 的迴歸防護。
        """
        uid = await _user(db, "t_sq04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        r = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改過的題幹",
                "options": [{"option_text": "很好"}, {"option_text": "普通"}],
                "version": row["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        question = detail["questions"][0]
        assert question["stem"] == "改過的題幹"
        assert [o["option_text"] for o in question["options"]] == ["很好", "普通"]
        assert [o["sort_order"] for o in question["options"]] == [1, 2]

        # 舊選項是**軟刪**而非消失
        deleted = await db.scalars(
            select(EtSurveyOption).where(EtSurveyOption.sq_id == row["sq_id"], EtSurveyOption.deleted == 1)
        )
        assert {o.option_text for o in deleted} == {"滿意", "普通", "不滿意"}

    async def test_刪除題目後順序遞補(self, client, db) -> None:
        """刪中間那題後，剩餘題目重編為 1..N。

        若 `UX_ET_SURVEY_QUESTION_ORDER` 不是部分索引，被軟刪的那列會繼續佔著
        原順序值，遞補時撞鍵。
        """
        uid = await _user(db, "t_sq05")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"], stem="第一題")
        q2 = await _add_question(client, uid, survey["survey_id"], stem="第二題")
        q3 = await _add_question(client, uid, survey["survey_id"], stem="第三題")
        assert [q1["sort_order"], q2["sort_order"], q3["sort_order"]] == [1, 2, 3]

        r = await client.delete(f"/api/et/survey-questions/{q2['sq_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text

        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert [(q["stem"], q["sort_order"]) for q in detail["questions"]] == [("第一題", 1), ("第三題", 2)]

    async def test_刪除題目連帶軟刪選項(self, client, db) -> None:
        uid = await _user(db, "t_sq06")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        await client.delete(f"/api/et/survey-questions/{row['sq_id']}", headers=_bearer(uid))

        alive = await db.scalars(
            select(EtSurveyOption).where(EtSurveyOption.sq_id == row["sq_id"], EtSurveyOption.deleted == 0)
        )
        assert list(alive) == []

    async def test_查無題目回_404(self, client, db) -> None:
        uid = await _user(db, "t_sq07")
        await _course(client, uid)
        r = await client.delete("/api/et/survey-questions/999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_SURVEY_005"


class TestSurveyQuestionTypes:
    """問答題型（#238）——推翻 data-model 原本的「題型一律單選（不設題型欄位）」。"""

    async def test_建立問答題(self, client, db) -> None:
        uid = await _user(db, "t_tp01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"], qtype=SURVEY_QUESTION_TEXT, options=[])
        assert row["question_type"] == SURVEY_QUESTION_TEXT
        assert row["options"] == []

    async def test_問答題帶選項被擋(self, client, db) -> None:
        """**明確擋下而非靜默忽略**——教師把單選改成問答時，選項若被無聲丟棄，
        他會以為還在。
        """
        uid = await _user(db, "t_tp02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(qtype=SURVEY_QUESTION_TEXT),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_008"

    async def test_單選題零選項仍被擋且錯誤碼不同(self, client, db) -> None:
        """`ET_SURVEY_004`（選項不足）與 `ET_SURVEY_008`（問答題帶選項）的修正方向
        相反，前端要靠 error_code 分辨。
        """
        uid = await _user(db, "t_tp03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(qtype=SURVEY_QUESTION_SINGLE, options=[]),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_004"

    async def test_未帶題型被擋(self, client, db) -> None:
        """`QUESTION_TYPE` 於 DB 與 model 皆無 default——漏傳要當場爆出來，
        不能靜默變成單選。
        """
        uid = await _user(db, "t_tp04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json={"stem": "no type", "options": _DEFAULT_OPTIONS},
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_單選改問答須一併清空選項(self, client, db) -> None:
        uid = await _user(db, "t_tp05")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])

        bad = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_TEXT,
                "stem": row["stem"],
                "options": _DEFAULT_OPTIONS,
                "version": row["version"],
            },
            headers=_bearer(uid),
        )
        assert bad.status_code == 422
        assert bad.json()["error_code"] == "ET_SURVEY_008"

        ok = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_TEXT,
                "stem": row["stem"],
                "options": [],
                "version": row["version"],
            },
            headers=_bearer(uid),
        )
        assert ok.status_code == 204, ok.text
        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert detail["questions"][0]["question_type"] == SURVEY_QUESTION_TEXT
        assert detail["questions"][0]["options"] == []

    async def test_兩種題型可混用(self, client, db) -> None:
        uid = await _user(db, "t_tp06")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _add_question(client, uid, survey["survey_id"], stem="single q")
        await _add_question(client, uid, survey["survey_id"], qtype=SURVEY_QUESTION_TEXT, stem="text q", options=[])

        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert [q["question_type"] for q in detail["questions"]] == [
            SURVEY_QUESTION_SINGLE,
            SURVEY_QUESTION_TEXT,
        ]


async def _set_course_status(db, course_id: int, status: str) -> None:
    """直接改課程狀態。

    受測的規則是 `ensure_survey_deletable(course.status)`——**重要的是狀態本身，
    不是怎麼變成那個狀態的**。走完整發布流程要複製 `test_et_publish.py` 的整套
    fixture（章節 + 教材 + 標籤 + 起訖時間 + 配分），那些跟本測試想驗的事無關，
    反而讓失敗時難以判斷是哪一環壞掉。
    """
    await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=status))
    await db.flush()


class TestSurveyDelete:
    """問卷刪除（#238 推翻 #204 之裁示 Q1）。"""

    async def test_刪除連帶軟刪題目與選項(self, client, db) -> None:
        uid = await _user(db, "t_dl01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])

        r = await client.delete(f"/api/et/surveys/{survey['survey_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text

        alive_q = await db.scalars(
            select(EtSurveyQuestion).where(
                EtSurveyQuestion.survey_id == survey["survey_id"], EtSurveyQuestion.deleted == 0
            )
        )
        alive_o = await db.scalars(
            select(EtSurveyOption).where(EtSurveyOption.sq_id == row["sq_id"], EtSurveyOption.deleted == 0)
        )
        assert list(alive_q) == []
        assert list(alive_o) == []

    async def test_刪除後可再次建立(self, client, db) -> None:
        """**釘住 `UX_ET_SURVEY_COURSE` 為部分唯一索引**（migration `8713c6177f6f`）。

        若仍是全表唯一約束，軟刪的那筆會永久佔住該課程——教師刪掉問卷後再也建不了，
        而錯誤訊息會是「一門課程僅可建立 1 份課後問卷」，指向一筆他看不見的資料。
        這正是 #204 在 `models.py` 註解裡預告的那個缺陷。
        """
        uid = await _user(db, "t_dl02")
        cid = await _course(client, uid)
        first = await _survey(client, uid, cid, "first")
        await client.delete(f"/api/et/surveys/{first['survey_id']}", headers=_bearer(uid))

        second = await _survey(client, uid, cid, "second")
        assert second["survey_id"] != first["survey_id"]
        assert second["survey_name"] == "second"

    @pytest.mark.parametrize("status", [COURSE_PUBLISHED, COURSE_CLOSED])
    async def test_非草稿課程不可刪除(self, client, db, status: str) -> None:
        """已關閉也擋：關閉可逆，再開課後學員的填答入口不該無故消失。"""
        uid = await _user(db, f"t_dl03{status[:3].lower()}")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _set_course_status(db, cid, status)

        r = await client.delete(f"/api/et/surveys/{survey['survey_id']}", headers=_bearer(uid))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_007"

    async def test_已發布課程仍可停用(self, client, db) -> None:
        """擋掉刪除但保留停用——否則已發布課程的問卷就完全動不了。"""
        uid = await _user(db, "t_dl04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _set_course_status(db, cid, COURSE_PUBLISHED)

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}",
            json={"survey_name": survey["survey_name"], "is_active": False, "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

    async def test_非擁有者不可刪除(self, client, db) -> None:
        owner = await _user(db, "t_dl05")
        other = await _user(db, "t_dl06")
        cid = await _course(client, owner)
        survey = await _survey(client, owner, cid)
        r = await client.delete(f"/api/et/surveys/{survey['survey_id']}", headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestSurveyTemplates:
    """模板套用（#238）。"""

    async def test_列出模板(self, client, db) -> None:
        uid = await _user(db, "t_tm01")
        r = await client.get("/api/et/survey-templates", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) >= 2
        assert all("question_count" in row and "questions" not in row for row in rows)

    async def test_套用模板建立整組題目(self, client, db) -> None:
        uid = await _user(db, "t_tm02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        templates = (await client.get("/api/et/survey-templates", headers=_bearer(uid))).json()
        target = templates[0]

        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/apply-template",
            json={"template_code": target["code"], "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["questions"]) == target["question_count"]
        assert [q["sort_order"] for q in body["questions"]] == list(range(1, target["question_count"] + 1))

    async def test_套用後題目可自由編修(self, client, db) -> None:
        """AC 8：套用後即為一般題目，與模板無關聯。"""
        uid = await _user(db, "t_tm03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        applied = (
            await client.post(
                f"/api/et/surveys/{survey['survey_id']}/apply-template",
                json={"template_code": "SATISFACTION", "version": survey["version"]},
                headers=_bearer(uid),
            )
        ).json()
        first = applied["questions"][0]

        r = await client.put(
            f"/api/et/survey-questions/{first['sq_id']}",
            json={
                "question_type": first["question_type"],
                "stem": "my own question",
                "options": _DEFAULT_OPTIONS,
                "version": first["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

    async def test_已有題目時不可套用(self, client, db) -> None:
        uid = await _user(db, "t_tm04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _add_question(client, uid, survey["survey_id"])

        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/apply-template",
            json={"template_code": "SATISFACTION", "version": detail["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_SURVEY_010"

    async def test_查無模板回_404(self, client, db) -> None:
        uid = await _user(db, "t_tm05")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/apply-template",
            json={"template_code": "NO_SUCH", "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_SURVEY_009"

    async def test_含問答題的模板可套用(self, client, db) -> None:
        """模板內容若違反自己的題型規則，套用時會被檢核擋下——這條走真實路徑確認
        `EFFECTIVENESS` 那組（含一題問答）確實建得起來。
        """
        uid = await _user(db, "t_tm06")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        body = (
            await client.post(
                f"/api/et/surveys/{survey['survey_id']}/apply-template",
                json={"template_code": "EFFECTIVENESS", "version": survey["version"]},
                headers=_bearer(uid),
            )
        ).json()
        types = [q["question_type"] for q in body["questions"]]
        assert SURVEY_QUESTION_TEXT in types
        text_q = next(q for q in body["questions"] if q["question_type"] == SURVEY_QUESTION_TEXT)
        assert text_q["options"] == []


class TestSurveyQuestionReorder:
    async def test_交換相鄰兩題(self, client, db) -> None:
        """**兩階段寫入**的核心測試——交換 1↔2 必然經過順序重複的中間狀態。

        逐列直接寫入會在第一列寫成 2 的瞬間撞上尚未更新的第二列，
        PostgreSQL 立即拋 `UniqueViolationError`（非 deferrable 之唯一索引逐列即時
        檢核，而部分索引無法宣告 deferrable）。
        """
        uid = await _user(db, "t_so01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"], stem="第一題")
        q2 = await _add_question(client, uid, survey["survey_id"], stem="第二題")

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}/questions/order",
            json={"question_ids": [q2["sq_id"], q1["sq_id"]], "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert [q["stem"] for q in detail["questions"]] == ["第二題", "第一題"]

    async def test_重排不遞增題目版本(self, client, db) -> None:
        """順序屬問卷結構——遞增題目自身 `VERSION` 會讓正在編輯該題的另一裝置
        無故衝突（FR-ET-US3-15）。
        """
        uid = await _user(db, "t_so02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"], stem="第一題")
        q2 = await _add_question(client, uid, survey["survey_id"], stem="第二題")

        await client.put(
            f"/api/et/surveys/{survey['survey_id']}/questions/order",
            json={"question_ids": [q2["sq_id"], q1["sq_id"]], "version": survey["version"]},
            headers=_bearer(uid),
        )
        detail = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert all(q["version"] == 0 for q in detail["questions"])
        # 問卷層版本才遞增
        assert detail["version"] == survey["version"] + 1

    async def test_重排清單不一致被擋(self, client, db) -> None:
        uid = await _user(db, "t_so03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"])
        await _add_question(client, uid, survey["survey_id"], stem="第二題")

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}/questions/order",
            json={"question_ids": [q1["sq_id"]], "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_006"

    async def test_版本不符回樂觀鎖錯誤(self, client, db) -> None:
        uid = await _user(db, "t_so04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"])

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}/questions/order",
            json={"question_ids": [q1["sq_id"]], "version": survey["version"] + 99},
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"


class TestSurveyFreeze:
    """AC 20 / 21：無填答可自由編修；有填答即凍結，僅可停用。"""

    async def test_無填答時可改題目(self, client, db) -> None:
        uid = await _user(db, "t_fz01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        r = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改過",
                "options": _DEFAULT_OPTIONS,
                "version": row["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

    async def test_有填答後新增題目被擋(self, client, db) -> None:
        uid = await _user(db, "t_fz02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _respond(db, survey["survey_id"])

        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_003"

    async def test_有填答後修改題目被擋(self, client, db) -> None:
        uid = await _user(db, "t_fz03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        await _respond(db, survey["survey_id"])

        r = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "偷改",
                "options": _DEFAULT_OPTIONS,
                "version": row["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_003"

    async def test_有填答後刪除題目被擋(self, client, db) -> None:
        uid = await _user(db, "t_fz04")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        await _respond(db, survey["survey_id"])

        r = await client.delete(f"/api/et/survey-questions/{row['sq_id']}", headers=_bearer(uid))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_003"

    async def test_有填答後重排被擋(self, client, db) -> None:
        uid = await _user(db, "t_fz05")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        q1 = await _add_question(client, uid, survey["survey_id"])
        await _respond(db, survey["survey_id"])

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}/questions/order",
            json={"question_ids": [q1["sq_id"]], "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_003"

    async def test_有填答後仍可停用問卷(self, client, db) -> None:
        """AC 21 明訂凍結後教師「僅可停用問卷」——若把停用也擋掉，
        凍結後整張卡片就變成死的，教師無路可走。
        """
        uid = await _user(db, "t_fz06")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _respond(db, survey["survey_id"])

        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}",
            json={"survey_name": survey["survey_name"], "is_active": False, "version": survey["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text

    async def test_凍結旗標與填答統計(self, client, db) -> None:
        uid = await _user(db, "t_fz07")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)

        before = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert before["frozen"] is False
        assert before["responded_count"] == 0

        await _respond(db, survey["survey_id"], "stu_a")
        await _respond(db, survey["survey_id"], "stu_b")

        after = (await client.get(f"{_COURSES}/{cid}/survey", headers=_bearer(uid))).json()
        assert after["frozen"] is True
        assert after["responded_count"] == 2
        # 尚無人加入課程（enrollment 屬 ET-4 / ET-8），未填人數不得為負
        assert after["pending_count"] == 0

    async def test_已軟刪之填答不觸發凍結(self, client, db) -> None:
        """凍結判定須排除 `DELETED = 1`——否則一筆被清掉的填答會讓問卷永久鎖死。"""
        uid = await _user(db, "t_fz08")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _respond(db, survey["survey_id"])
        # 用 ORM 層 `update()` 而非 `__table__.update()`——後者的 values 必須用
        # DB 欄位名（`DELETED`），寫 ORM 屬性名會以 CompileError 收場。
        await db.execute(
            update(EtSurveyResponseM).where(EtSurveyResponseM.survey_id == survey["survey_id"]).values(deleted=1)
        )
        await db.flush()

        r = await client.post(
            f"/api/et/surveys/{survey['survey_id']}/questions",
            json=_question_body(),
            headers=_bearer(uid),
        )
        assert r.status_code == 201, r.text


class TestSurveyOptimisticLock:
    async def test_問卷本體版本不符被擋(self, client, db) -> None:
        """AC 31 / FR-ET-US3-15：問卷本體維護自己的 `VERSION`。"""
        uid = await _user(db, "t_lk01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.put(
            f"/api/et/surveys/{survey['survey_id']}",
            json={"survey_name": "改名", "is_active": True, "version": survey["version"] + 5},
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_題目版本不符被擋(self, client, db) -> None:
        uid = await _user(db, "t_lk02")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])
        r = await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改",
                "options": _DEFAULT_OPTIONS,
                "version": row["version"] + 5,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_版本衝突時選項未被換掉(self, client, db) -> None:
        """`replace_question` 先更題目再換選項——版本不符時 rowcount 為 0，
        此時不該已經把選項刪掉。
        """
        uid = await _user(db, "t_lk03")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        row = await _add_question(client, uid, survey["survey_id"])

        await client.put(
            f"/api/et/survey-questions/{row['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改",
                "options": [{"option_text": "X"}, {"option_text": "Y"}],
                "version": 99,
            },
            headers=_bearer(uid),
        )
        alive = await db.scalars(
            select(EtSurveyOption).where(EtSurveyOption.sq_id == row["sq_id"], EtSurveyOption.deleted == 0)
        )
        assert {o.option_text for o in alive} == {"滿意", "普通", "不滿意"}


class TestSurveyPersistence:
    async def test_題目與選項確實寫入資料庫(self, client, db) -> None:
        uid = await _user(db, "t_ps01")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        await _add_question(client, uid, survey["survey_id"])

        questions = list(
            await db.scalars(
                select(EtSurveyQuestion).where(
                    EtSurveyQuestion.survey_id == survey["survey_id"], EtSurveyQuestion.deleted == 0
                )
            )
        )
        assert len(questions) == 1
        assert questions[0].created_user == uid
