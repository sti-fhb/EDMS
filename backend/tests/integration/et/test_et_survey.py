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
from app.et.constants import ROLE_TEACHER
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


def _question_body(*, stem="您對本課程是否滿意？", options=None) -> dict:
    """組題目請求。

    ⚠️ 以 `is None` 判斷而非 `options or 預設`——**空陣列是 falsy**，用 `or` 會讓
    「明確傳入 0 個選項」被預設值吃掉，那條測試就變成假綠（測到的是 3 個選項）。
    比照 `test_et_quiz.py` 之同型修正。
    """
    return {"stem": stem, "options": _DEFAULT_OPTIONS if options is None else options}


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

    async def test_沒有刪除問卷的端點(self, client, db) -> None:
        """SA 裁示 #204 Q1 → B：問卷只能停用、不可刪除。

        這條同時是 `UQ_ET_SURVEY_COURSE` 維持全表唯一（未排除軟刪除列）的前提——
        若日後有人加上刪除端點而忘了改索引，本測試會先失敗，提醒去看
        `models.py` 該約束上方的註解。
        """
        uid = await _user(db, "t_srv07")
        cid = await _course(client, uid)
        survey = await _survey(client, uid, cid)
        r = await client.delete(f"/api/et/surveys/{survey['survey_id']}", headers=_bearer(uid))
        assert r.status_code == 405


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
            json={"stem": "改過", "options": _DEFAULT_OPTIONS, "version": row["version"]},
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
            json={"stem": "偷改", "options": _DEFAULT_OPTIONS, "version": row["version"]},
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
            json={"stem": "改", "options": _DEFAULT_OPTIONS, "version": row["version"] + 5},
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
            json={"stem": "改", "options": [{"option_text": "X"}, {"option_text": "Y"}], "version": 99},
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
