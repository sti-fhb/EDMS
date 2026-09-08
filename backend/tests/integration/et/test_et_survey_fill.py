"""ET05 課後問卷填寫整合測試（US13 / #284）——學員端。

入口四態導出與作答驗證已在 `tests/unit/et/test_survey_fill_rules.py` 以純函式涵蓋。
此處只驗**需要真 DB 才驗得了**的事：

1. `(SURVEY_ID, USER_ID)` 唯一真的擋得住重複送出（那條約束在此之前從未被觸發）
2. **`_D` 實際寫了幾列**——SA Q1 裁示 A「留空的問答題不寫列」的唯一驗證點
3. `/learn` 的 `survey` 區塊接線與四態
4. **題目凍結（`ET_SURVEY_003`）第一次真正生效**——#204 寫下規則，但在此之前沒有
   任何路徑能寫入 `ET_SURVEY_RESPONSE_M`，那條凍結是自然成立、從未被驗證的
5. 在籍與非在籍的授權邊界
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
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
    SURVEY_QUESTION_SINGLE,
    SURVEY_QUESTION_TEXT,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.roles.models import EtUserRole
from app.et.survey.models import EtSurvey, EtSurveyResponseD, EtSurveyResponseM

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


def _form_url(course_id: int) -> str:
    return f"/api/et/courses/{course_id}/survey/form"


def _submit_url(course_id: int) -> str:
    return f"/api/et/courses/{course_id}/survey/response"


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


async def _course(client, db, teacher: str, *, status: str = COURSE_PUBLISHED) -> int:
    """已發布課程 + 一章一項目。

    刻意**不走發布 API**：那需要備妥標籤、起訖時間與配分才過得了六項檢核（#204），
    而本檔要驗的是問卷填寫。走發布 API 會讓每條測試綁著那些規則。
    """
    created = await client.post(_COURSES, json={"course_name": "採血作業新進人員訓練"}, headers=_bearer(teacher))
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]
    now = utcnow()
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(status=status, open_start_at=now.replace(microsecond=0))
    )
    await db.flush()
    return course_id


async def _item(client, teacher: str, course_id: int, *, name: str = "第一章") -> int:
    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": name}, headers=_bearer(teacher)
    )
    assert chapter.status_code == 201, chapter.text
    item = await client.post(
        f"/api/et/chapters/{chapter.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text
    return item.json()["item_id"]


async def _enroll(db, user_id: str, course_id: int) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _complete(db, user_id: str, course_id: int, item_id: int) -> None:
    db.add(
        EtProgress(
            user_id=user_id,
            course_id=course_id,
            item_id=item_id,
            is_completed=True,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


async def _survey(client, teacher: str, course_id: int, *, with_text: bool = True) -> dict:
    """建問卷：2 題單選 + （選配）1 題問答。回 `{survey_id, questions: [...]}`。"""
    created = await client.post(
        f"{_COURSES}/{course_id}/survey", json={"survey_name": "課後滿意度問卷"}, headers=_bearer(teacher)
    )
    assert created.status_code == 201, created.text
    survey_id = created.json()["survey_id"]
    for stem, options in (
        ("整體而言，您對本課程的內容安排是否滿意？", ["滿意", "普通", "不滿意"]),
        ("影片教材的清晰度與長度是否適當？", ["適當", "普通", "需改進"]),
    ):
        r = await client.post(
            f"/api/et/surveys/{survey_id}/questions",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": stem,
                "options": [{"option_text": o} for o in options],
            },
            headers=_bearer(teacher),
        )
        assert r.status_code == 201, r.text
    if with_text:
        r = await client.post(
            f"/api/et/surveys/{survey_id}/questions",
            json={"question_type": SURVEY_QUESTION_TEXT, "stem": "其他建議", "options": []},
            headers=_bearer(teacher),
        )
        assert r.status_code == 201, r.text
    detail = await client.get(f"{_COURSES}/{course_id}/survey", headers=_bearer(teacher))
    assert detail.status_code == 200, detail.text
    return detail.json()


async def _ready(client, db, tag: str, *, with_text: bool = True, completed: bool = True) -> dict:
    """一位已在籍（可選已完課）的學員 + 一門有問卷的已發布課程。"""
    teacher = await _user(db, f"t_{tag}", ROLE_TEACHER)
    student = await _user(db, f"s_{tag}")
    course_id = await _course(client, db, teacher)
    item_id = await _item(client, teacher, course_id)
    survey = await _survey(client, teacher, course_id, with_text=with_text)
    await _enroll(db, student, course_id)
    if completed:
        await _complete(db, student, course_id, item_id)
    return {
        "teacher": teacher,
        "student": student,
        "course_id": course_id,
        "item_id": item_id,
        "survey": survey,
        "questions": survey["questions"],
    }


def _single_answers(questions: list[dict]) -> list[dict]:
    """所有單選題各選第一個選項。"""
    return [
        {"sq_id": q["sq_id"], "so_id": q["options"][0]["so_id"]}
        for q in questions
        if q["question_type"] == SURVEY_QUESTION_SINGLE
    ]


class TestEntryState:
    """AC 1 / AC 2 / AC 10 / AC 11：`/learn` 之 `survey` 區塊。"""

    async def test_完課且問卷啟用時為可填(self, client, db) -> None:
        ctx = await _ready(client, db, "ent01")

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.status_code == 200, r.text
        assert r.json()["survey"]["state"] == "FILLABLE"
        assert r.json()["survey"]["survey_name"] == "課後滿意度問卷"

    async def test_未完課時為隱藏(self, client, db) -> None:
        ctx = await _ready(client, db, "ent02", completed=False)

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.json()["survey"]["state"] == "HIDDEN"

    async def test_課程無問卷時為_null(self, client, db) -> None:
        """AC 2：問卷為選配（AC 23），「沒有」是正常狀態、不是錯誤。"""
        teacher = await _user(db, "t_ent03", ROLE_TEACHER)
        student = await _user(db, "s_ent03")
        course_id = await _course(client, db, teacher)
        item_id = await _item(client, teacher, course_id)
        await _enroll(db, student, course_id)
        await _complete(db, student, course_id, item_id)

        r = await client.get(f"{_COURSES}/{course_id}/learn", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["survey"] is None

    async def test_問卷停用時為隱藏(self, client, db) -> None:
        ctx = await _ready(client, db, "ent04")
        await db.execute(
            update(EtSurvey).where(EtSurvey.survey_id == ctx["survey"]["survey_id"]).values(is_active=False)
        )
        await db.flush()

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.json()["survey"]["state"] == "HIDDEN"

    async def test_已填後為已送出並帶送出時間(self, client, db) -> None:
        ctx = await _ready(client, db, "ent05")
        submitted = await client.post(
            _submit_url(ctx["course_id"]),
            json={"answers": _single_answers(ctx["questions"])},
            headers=_bearer(ctx["student"]),
        )
        assert submitted.status_code == 201, submitted.text

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.json()["survey"]["state"] == "SUBMITTED"
        assert r.json()["survey"]["submitted_at"] is not None

    async def test_課程關閉且未填為關閉態(self, client, db) -> None:
        ctx = await _ready(client, db, "ent06")
        await _close(db, ctx["course_id"])

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.json()["survey"]["state"] == "COURSE_CLOSED"

    async def test_課程關閉但已填仍為已送出(self, client, db) -> None:
        """AC 11：關閉不影響已填者的回看。"""
        ctx = await _ready(client, db, "ent07")
        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": _single_answers(ctx["questions"])},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201
        await _close(db, ctx["course_id"])

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert r.json()["survey"]["state"] == "SUBMITTED"

    async def test_教師預覽不顯示入口(self, client, db) -> None:
        """擁有者沒有進度可累積，導不出完課，入口自然不出現。

        釘住這件事是因為它是**自然成立**而非明寫的判定——若日後有人為教師預覽補上
        假的完成集合，這條會先紅。
        """
        ctx = await _ready(client, db, "ent08")

        r = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["teacher"]))

        assert r.status_code == 200, r.text
        assert r.json()["survey"]["state"] == "HIDDEN"


class TestGetForm:
    async def test_回題目與選項並依序(self, client, db) -> None:
        ctx = await _ready(client, db, "frm01")

        r = await client.get(_form_url(ctx["course_id"]), headers=_bearer(ctx["student"]))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "FILLABLE"
        assert [q["question_type"] for q in body["questions"]] == [
            SURVEY_QUESTION_SINGLE,
            SURVEY_QUESTION_SINGLE,
            SURVEY_QUESTION_TEXT,
        ]
        assert [o["option_text"] for o in body["questions"][0]["options"]] == ["滿意", "普通", "不滿意"]
        assert body["questions"][2]["options"] == [], "問答題不得有選項（ET_SURVEY_008）"
        assert body["my_answers"] == []

    async def test_非在籍者回403(self, client, db) -> None:
        ctx = await _ready(client, db, "frm02")
        outsider = await _user(db, "s_frm02b")

        r = await client.get(_form_url(ctx["course_id"]), headers=_bearer(outsider))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_SURVEY_011"

    async def test_課程無問卷回404(self, client, db) -> None:
        teacher = await _user(db, "t_frm03", ROLE_TEACHER)
        student = await _user(db, "s_frm03")
        course_id = await _course(client, db, teacher)
        await _enroll(db, student, course_id)

        r = await client.get(_form_url(course_id), headers=_bearer(student))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_SURVEY_001"

    async def test_非在籍優先於問卷存在性(self, client, db) -> None:
        """否則任一登入者可用它問出「哪些課程建了問卷」——那是課程結構的資訊。"""
        teacher = await _user(db, "t_frm04", ROLE_TEACHER)
        outsider = await _user(db, "s_frm04")
        course_id = await _course(client, db, teacher)

        r = await client.get(_form_url(course_id), headers=_bearer(outsider))

        assert r.status_code == 403, "課程沒有問卷，但非在籍者不該因此得知"
        assert r.json()["error_code"] == "ET_SURVEY_011"

    async def test_未完課仍可取表單且狀態為隱藏(self, client, db) -> None:
        """讀取端點對 `HIDDEN` 回 200——它只表示側欄不顯示入口。

        回錯誤會讓「完課回退後想回看自己填答」（FR-08）那條路徑連帶做成錯誤畫面。
        """
        ctx = await _ready(client, db, "frm05", completed=False)

        r = await client.get(_form_url(ctx["course_id"]), headers=_bearer(ctx["student"]))

        assert r.status_code == 200, r.text
        assert r.json()["state"] == "HIDDEN"
        assert len(r.json()["questions"]) == 3, "題目照常回——狀態決定能不能改，不是能不能看"


class TestSubmit:
    async def test_送出寫入具名主檔與明細(self, client, db) -> None:
        """AC 4 / AC 7。"""
        ctx = await _ready(client, db, "sub01")
        answers = _single_answers(ctx["questions"])
        text_q = ctx["questions"][2]

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={"answers": [*answers, {"sq_id": text_q["sq_id"], "answer_text": "影片可以再短一些"}]},
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 201, r.text
        assert r.json()["submitted_at"] is not None
        master = await db.scalar(
            select(EtSurveyResponseM).where(EtSurveyResponseM.survey_id == ctx["survey"]["survey_id"])
        )
        assert master is not None
        assert master.user_id == ctx["student"], "具名"
        rows = (
            await db.scalars(
                select(EtSurveyResponseD)
                .where(EtSurveyResponseD.response_id == master.response_id)
                .order_by(EtSurveyResponseD.sq_id)
            )
        ).all()
        assert len(rows) == 3
        assert [r.so_id is not None for r in rows] == [True, True, False]
        assert rows[2].answer_text == "影片可以再短一些"

    async def test_問答題留空時明細不含該題(self, client, db) -> None:
        """🔴 SA Q1 裁示 A 的唯一驗證點——`_D` 只記錄實際有作答的題目。

        寫了空列的話 US9 的「問答題僅計已答人數」會把沒意見的人算成有回饋的人，
        而且不會報錯、只會靜默算錯。
        """
        ctx = await _ready(client, db, "sub02")

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={"answers": _single_answers(ctx["questions"])},
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 201, r.text
        rows = await _detail_rows(db, ctx["survey"]["survey_id"])
        assert len(rows) == 2, "3 題問卷、問答題留空 → 只有 2 列"
        assert all(row.answer_text is None for row in rows)

    async def test_問答題只打空白時明細不含該題(self, client, db) -> None:
        ctx = await _ready(client, db, "sub03")

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={
                "answers": [
                    *_single_answers(ctx["questions"]),
                    {"sq_id": ctx["questions"][2]["sq_id"], "answer_text": "   "},
                ]
            },
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 201, r.text
        assert len(await _detail_rows(db, ctx["survey"]["survey_id"])) == 2

    async def test_重複送出回409(self, client, db) -> None:
        """AC 5：`UQ_ET_SURVEY_RESPONSE_SURVEY_USER` 真的擋得住。

        那條約束在 #284 之前從未被觸發（沒有任何路徑能寫入 `_M`），此為第一次驗證。
        """
        ctx = await _ready(client, db, "sub04")
        payload = {"answers": _single_answers(ctx["questions"])}
        assert (
            await client.post(_submit_url(ctx["course_id"]), json=payload, headers=_bearer(ctx["student"]))
        ).status_code == 201

        again = await client.post(_submit_url(ctx["course_id"]), json=payload, headers=_bearer(ctx["student"]))

        assert again.status_code == 409
        assert again.json()["error_code"] == "ET_SURVEY_013"
        assert len(await _detail_rows(db, ctx["survey"]["survey_id"])) == 2, "第二次不該留下任何明細"

    async def test_未完課送出回403(self, client, db) -> None:
        ctx = await _ready(client, db, "sub05", completed=False)

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={"answers": _single_answers(ctx["questions"])},
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_SURVEY_012"

    async def test_課程關閉送出回409(self, client, db) -> None:
        """AC 10。"""
        ctx = await _ready(client, db, "sub06")
        await _close(db, ctx["course_id"])

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={"answers": _single_answers(ctx["questions"])},
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_SURVEY_014"

    async def test_單選題漏答回422並帶題號(self, client, db) -> None:
        ctx = await _ready(client, db, "sub07")
        answers = _single_answers(ctx["questions"])

        r = await client.post(
            _submit_url(ctx["course_id"]), json={"answers": answers[:1]}, headers=_bearer(ctx["student"])
        )

        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_015"

    async def test_送出別題之選項回422(self, client, db) -> None:
        """防止 US9 的統計出現不屬於該題的選項。"""
        ctx = await _ready(client, db, "sub08")
        q1, q2 = ctx["questions"][0], ctx["questions"][1]

        r = await client.post(
            _submit_url(ctx["course_id"]),
            json={
                "answers": [
                    {"sq_id": q1["sq_id"], "so_id": q2["options"][0]["so_id"]},
                    {"sq_id": q2["sq_id"], "so_id": q2["options"][0]["so_id"]},
                ]
            },
            headers=_bearer(ctx["student"]),
        )

        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_SURVEY_017"

    async def test_失敗之送出不留下主檔(self, client, db) -> None:
        """驗證不合規的送出**完全不寫入**——否則學員會有一筆空的填答，且再也不能填。"""
        ctx = await _ready(client, db, "sub09")

        assert (
            await client.post(_submit_url(ctx["course_id"]), json={"answers": []}, headers=_bearer(ctx["student"]))
        ).status_code == 422

        master = await db.scalar(
            select(EtSurveyResponseM).where(EtSurveyResponseM.survey_id == ctx["survey"]["survey_id"])
        )
        assert master is None


class TestReadBack:
    async def test_已填者取回自己的作答(self, client, db) -> None:
        """AC 6 / AC 9：唯讀回看。"""
        ctx = await _ready(client, db, "rdb01")
        answers = _single_answers(ctx["questions"])
        text_q = ctx["questions"][2]
        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": [*answers, {"sq_id": text_q["sq_id"], "answer_text": "希望增加實作演練"}]},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201

        r = await client.get(_form_url(ctx["course_id"]), headers=_bearer(ctx["student"]))

        body = r.json()
        assert body["state"] == "SUBMITTED"
        assert len(body["my_answers"]) == 3
        assert body["my_answers"][2]["answer_text"] == "希望增加實作演練"

    async def test_留空之問答題不出現於回看清單(self, client, db) -> None:
        ctx = await _ready(client, db, "rdb02")
        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": _single_answers(ctx["questions"])},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201

        body = (await client.get(_form_url(ctx["course_id"]), headers=_bearer(ctx["student"]))).json()

        assert len(body["my_answers"]) == 2
        assert len(body["questions"]) == 3, "題目照常三題——前端據此把該題呈現為未填"

    async def test_只回自己的作答不含他人(self, client, db) -> None:
        """問卷具名，但學員只該看到自己填的。"""
        ctx = await _ready(client, db, "rdb03")
        other = await _user(db, "s_rdb03b")
        await _enroll(db, other, ctx["course_id"])
        await _complete(db, other, ctx["course_id"], ctx["item_id"])
        for who in (ctx["student"], other):
            assert (
                await client.post(
                    _submit_url(ctx["course_id"]),
                    json={"answers": _single_answers(ctx["questions"])},
                    headers=_bearer(who),
                )
            ).status_code == 201

        body = (await client.get(_form_url(ctx["course_id"]), headers=_bearer(other))).json()

        assert len(body["my_answers"]) == 2
        master = await db.scalar(
            select(EtSurveyResponseM).where(
                EtSurveyResponseM.survey_id == ctx["survey"]["survey_id"],
                EtSurveyResponseM.user_id == other,
            )
        )
        assert master is not None

    async def test_完課回退後仍為已送出且不可重填(self, client, db) -> None:
        """AC 13 / FR-ET-US13-08：教師新增章節致完課回退，已填問卷**不失效**。"""
        ctx = await _ready(client, db, "rdb04")
        payload = {"answers": _single_answers(ctx["questions"])}
        assert (
            await client.post(_submit_url(ctx["course_id"]), json=payload, headers=_bearer(ctx["student"]))
        ).status_code == 201
        await _item(client, ctx["teacher"], ctx["course_id"], name="第二章")

        form = (await client.get(_form_url(ctx["course_id"]), headers=_bearer(ctx["student"]))).json()
        again = await client.post(_submit_url(ctx["course_id"]), json=payload, headers=_bearer(ctx["student"]))

        assert form["state"] == "SUBMITTED", "完課回退不使已填問卷失效"
        assert len(form["my_answers"]) == 2
        assert again.status_code == 409
        assert again.json()["error_code"] == "ET_SURVEY_013"


class TestQuestionFreeze:
    """`ET_SURVEY_003`（#204）在本 issue **第一次真正生效**。

    在此之前沒有任何路徑能寫入 `ET_SURVEY_RESPONSE_M`，那條凍結是自然成立、從未被
    驗證的——與 #274 對 #255 兩條裁示的關係相同（前一張 issue 寫下規則，要等後一張
    提供資料才會被觸發）。
    """

    async def test_學員填答後教師改題目被擋(self, client, db) -> None:
        ctx = await _ready(client, db, "frz01")
        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": _single_answers(ctx["questions"])},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201

        r = await client.put(
            f"/api/et/survey-questions/{ctx['questions'][0]['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改過的題幹",
                "options": [{"option_text": "是"}, {"option_text": "否"}],
                "version": ctx["questions"][0]["version"],
            },
            headers=_bearer(ctx["teacher"]),
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_SURVEY_003"

    async def test_學員填答後教師仍可停用問卷(self, client, db) -> None:
        """凍結**不涵蓋** `IS_ACTIVE`（AC 21）——連停用都擋掉會使凍結後無路可走。"""
        ctx = await _ready(client, db, "frz02")
        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": _single_answers(ctx["questions"])},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201

        r = await client.put(
            f"/api/et/surveys/{ctx['survey']['survey_id']}",
            json={
                "survey_name": "課後滿意度問卷",
                "is_active": False,
                "version": ctx["survey"]["version"],
            },
            headers=_bearer(ctx["teacher"]),
        )

        assert r.status_code == 204, r.text


class TestNoProgressSideEffect:
    """AC 8 / FR-ET-US13-07：填寫問卷**不計入**學習進度、**不是**完課條件。"""

    async def test_送出問卷不改變進度與完課狀態(self, client, db) -> None:
        ctx = await _ready(client, db, "nse01")
        before = (await client.get("/api/et/my-courses", headers=_bearer(ctx["student"]))).json()

        assert (
            await client.post(
                _submit_url(ctx["course_id"]),
                json={"answers": _single_answers(ctx["questions"])},
                headers=_bearer(ctx["student"]),
            )
        ).status_code == 201

        after = (await client.get("/api/et/my-courses", headers=_bearer(ctx["student"]))).json()
        assert before["summary"] == after["summary"]
        assert before["courses"][0]["progress_pct"] == after["courses"][0]["progress_pct"]
        rows = (await db.scalars(select(EtProgress).where(EtProgress.course_id == ctx["course_id"]))).all()
        assert len(rows) == 1, "問卷不產生 ET_PROGRESS 列"


async def _close(db, course_id: int) -> None:
    await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_CLOSED))
    await db.flush()


async def _detail_rows(db, survey_id: int) -> list[EtSurveyResponseD]:
    return list(
        (
            await db.scalars(
                select(EtSurveyResponseD)
                .join(EtSurveyResponseM, EtSurveyResponseM.response_id == EtSurveyResponseD.response_id)
                .where(EtSurveyResponseM.survey_id == survey_id)
                .order_by(EtSurveyResponseD.sq_id)
            )
        ).all()
    )
