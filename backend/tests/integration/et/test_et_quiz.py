"""ET02 測驗設定與題目整合測試（US3 / #203）。

重點在需要真 DB 才驗得了的事：

1. 測驗設定之兩態語意（`TIME_LIMIT_MIN` 空白 = 不限時、`MAX_RETRY` 0 = 不允許重考）
2. 題目與選項的全量覆寫、順序遞補
3. **刪除題目時學員作答明細之連帶軟刪除**——須先建作答測資才驗得出
4. 樂觀鎖粒度：題目重排帶測驗層 version，不動題目自身 version
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import ATTEMPT_IN_PROGRESS, ITEM_QUIZ, QUESTION_MULTIPLE, QUESTION_SINGLE, ROLE_TEACHER
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM
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


async def _quiz(client, uid: str) -> tuple[int, int]:
    """建課程 → 章節 → 測驗項目，回 `(course_id, quiz_id)`。"""
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考"},
        headers=_bearer(uid),
    )
    return cid, item.json()["quiz_id"]


_DEFAULT_OPTIONS = [
    {"option_text": "A", "is_correct": True},
    {"option_text": "B", "is_correct": False},
]


def _question_body(*, qtype=QUESTION_SINGLE, stem="題幹", points=100, options=None) -> dict:
    """組題目請求。

    ⚠️ 以 `is None` 判斷而非 `options or 預設`——**空陣列是 falsy**，用 `or` 會讓
    「明確傳入 0 個選項」被預設值吃掉，那條測試就變成假綠（測到的是 2 個選項）。
    """
    return {
        "question_type": qtype,
        "stem": stem,
        "points": points,
        "options": _DEFAULT_OPTIONS if options is None else options,
    }


async def _add_question(client, uid: str, quiz_id: int, **kwargs) -> dict:
    r = await client.post(f"/api/et/quizzes/{quiz_id}/questions", json=_question_body(**kwargs), headers=_bearer(uid))
    assert r.status_code == 201, r.text
    return r.json()


class TestQuizSettings:
    async def test_空殼測驗帶預設值(self, client, db) -> None:
        uid = await _user(db, "ETQ_S1")
        _, qid = await _quiz(client, uid)
        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["pass_score"], body["max_retry"]) == (80, 3)
        assert body["time_limit_min"] is None, "預設空白 = 不限時"
        assert body["description"] is None
        assert body["questions"] == [] and body["points_total"] == 0

    async def test_更新設定含純文字說明(self, client, db) -> None:
        """SA 裁示 #203 Q1：測驗說明為**純文字**，不走 HTML 消毒。"""
        uid = await _user(db, "ETQ_S2")
        _, qid = await _quiz(client, uid)
        r = await client.put(
            f"/api/et/quizzes/{qid}",
            json={
                "quiz_name": "期末考",
                "description": "請於 30 分鐘內完成，<b>不會</b>被當成 HTML",
                "pass_score": 60,
                "time_limit_min": 30,
                "max_retry": 0,
                "version": 0,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))
        assert quiz.quiz_name == "期末考"
        assert quiz.description == "請於 30 分鐘內完成，<b>不會</b>被當成 HTML", "純文字欄位不得被消毒改寫"
        assert (quiz.pass_score, quiz.time_limit_min, quiz.max_retry, quiz.version) == (60, 30, 0, 1)

    async def test_說明全空白視同未填(self, client, db) -> None:
        uid = await _user(db, "ETQ_S3")
        _, qid = await _quiz(client, uid)
        await client.put(
            f"/api/et/quizzes/{qid}",
            json={
                "quiz_name": "考試",
                "description": "   ",
                "pass_score": 80,
                "time_limit_min": None,
                "max_retry": 3,
                "version": 0,
            },
            headers=_bearer(uid),
        )
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))
        assert quiz.description is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("pass_score", -1),
            ("pass_score", 101),
            ("max_retry", -1),
            ("max_retry", 1000),
            ("time_limit_min", 0),
            ("time_limit_min", -5),
        ],
    )
    async def test_設定值超出範圍被擋(self, client, db, field: str, value: int) -> None:
        """`time_limit_min` 為兩態：空白 = 不限時、>= 1 = 限時。0 不是有效值。"""
        uid = await _user(db, f"ETQ_R{abs(hash((field, value))) % 1000}")
        _, qid = await _quiz(client, uid)
        payload = {
            "quiz_name": "考試",
            "description": None,
            "pass_score": 80,
            "time_limit_min": None,
            "max_retry": 3,
            "version": 0,
        }
        payload[field] = value
        r = await client.put(f"/api/et/quizzes/{qid}", json=payload, headers=_bearer(uid))
        assert r.status_code == 422

    async def test_版本不符回_409(self, client, db) -> None:
        uid = await _user(db, "ETQ_S4")
        _, qid = await _quiz(client, uid)
        r = await client.put(
            f"/api/et/quizzes/{qid}",
            json={
                "quiz_name": "考試",
                "description": None,
                "pass_score": 80,
                "time_limit_min": None,
                "max_retry": 3,
                "version": 99,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_非擁有者不可讀取(self, client, db) -> None:
        """回應含 `is_correct`（正確答案）——非擁有者讀得到等於答案外洩。"""
        owner = await _user(db, "ETQ_S5")
        other = await _user(db, "ETQ_S6")
        _, qid = await _quiz(client, owner)
        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(other))
        assert r.status_code == 403

    async def test_查無測驗回_404(self, client, db) -> None:
        uid = await _user(db, "ETQ_S7")
        r = await client.get("/api/et/quizzes/999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_QUIZ_001"


class TestQuestions:
    async def test_新增題目與選項同一請求(self, client, db) -> None:
        uid = await _user(db, "ETQ_Q1")
        _, qid = await _quiz(client, uid)
        body = await _add_question(client, uid, qid)
        assert body["sort_order"] == 1
        assert [o["option_text"] for o in body["options"]] == ["A", "B"]
        assert [o["is_correct"] for o in body["options"]] == [True, False]
        assert [o["sort_order"] for o in body["options"]] == [1, 2]

    async def test_配分總和由後端算出(self, client, db) -> None:
        """AC：UI 需常駐顯示「90 / 100」。不等於 100 **不在此阻擋**（屬 #204 發布檢核）。"""
        uid = await _user(db, "ETQ_Q2")
        _, qid = await _quiz(client, uid)
        await _add_question(client, uid, qid, points=40)
        await _add_question(client, uid, qid, points=50)
        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        assert r.json()["points_total"] == 90, "總和 90 應如實回報，不阻擋儲存"

    async def test_多選題無正確選項被擋(self, client, db) -> None:
        """ET-MSG-ET02-004；data-model：避免部分計分公式分母為 0。"""
        uid = await _user(db, "ETQ_Q3")
        _, qid = await _quiz(client, uid)
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(
                qtype=QUESTION_MULTIPLE,
                options=[
                    {"option_text": "A", "is_correct": False},
                    {"option_text": "B", "is_correct": False},
                ],
            ),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_QUESTION_002"

    async def test_單選題兩個正確選項被擋(self, client, db) -> None:
        """spec 未明訂單選題，但兩個正確答案會讓計分無從定義（SD 補上之規則）。"""
        uid = await _user(db, "ETQ_Q4")
        _, qid = await _quiz(client, uid)
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(
                qtype=QUESTION_SINGLE,
                options=[
                    {"option_text": "A", "is_correct": True},
                    {"option_text": "B", "is_correct": True},
                ],
            ),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_QUESTION_002"

    async def test_多選題可有多個正確選項(self, client, db) -> None:
        uid = await _user(db, "ETQ_Q5")
        _, qid = await _quiz(client, uid)
        body = await _add_question(
            client,
            uid,
            qid,
            qtype=QUESTION_MULTIPLE,
            options=[
                {"option_text": "A", "is_correct": True},
                {"option_text": "B", "is_correct": True},
                {"option_text": "C", "is_correct": False},
            ],
        )
        assert sum(1 for o in body["options"] if o["is_correct"]) == 2

    @pytest.mark.parametrize("count", [0, 1])
    async def test_選項數不足被擋(self, client, db, count: int) -> None:
        uid = await _user(db, f"ETQ_O{count}")
        _, qid = await _quiz(client, uid)
        options = [{"option_text": f"O{i}", "is_correct": i == 0} for i in range(count)]
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(options=options),
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_QUESTION_003"

    async def test_選項數超過六個被擋(self, client, db) -> None:
        uid = await _user(db, "ETQ_O7")
        _, qid = await _quiz(client, uid)
        options = [{"option_text": f"O{i}", "is_correct": i == 0} for i in range(7)]
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(options=options),
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_更新題目全量覆寫選項(self, client, db) -> None:
        """舊選項軟刪、新選項插入——作答紀錄以 snapshot 保存，不受影響。"""
        uid = await _user(db, "ETQ_U1")
        _, qid = await _quiz(client, uid)
        question = await _add_question(client, uid, qid)

        r = await client.put(
            f"/api/et/questions/{question['question_id']}",
            json={
                **_question_body(
                    stem="改過的題幹",
                    points=50,
                    options=[
                        {"option_text": "X", "is_correct": False},
                        {"option_text": "Y", "is_correct": True},
                        {"option_text": "Z", "is_correct": False},
                    ],
                ),
                "version": 0,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        detail = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        got = detail.json()["questions"][0]
        assert got["stem"] == "改過的題幹" and got["points"] == 50 and got["version"] == 1
        assert [o["option_text"] for o in got["options"]] == ["X", "Y", "Z"]

        all_options = list(await db.scalars(select(EtOption).where(EtOption.question_id == question["question_id"])))
        assert sum(1 for o in all_options if o.deleted == 1) == 2, "舊選項應軟刪而非硬刪"

    async def test_更新題目版本不符時不動選項(self, client, db) -> None:
        """先更題目再換選項——版本不符時不該已經把選項換掉。"""
        uid = await _user(db, "ETQ_U2")
        _, qid = await _quiz(client, uid)
        question = await _add_question(client, uid, qid)

        r = await client.put(
            f"/api/et/questions/{question['question_id']}",
            json={
                **_question_body(options=[{"option_text": "新", "is_correct": True}, {"option_text": "選項"}]),
                "version": 99,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        detail = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        assert [o["option_text"] for o in detail.json()["questions"][0]["options"]] == ["A", "B"]

    async def test_題幹超長被擋(self, client, db) -> None:
        uid = await _user(db, "ETQ_U3")
        _, qid = await _quiz(client, uid)
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(stem="長" * 501),
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_未知題型被擋(self, client, db) -> None:
        uid = await _user(db, "ETQ_U4")
        _, qid = await _quiz(client, uid)
        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            json=_question_body(qtype="ESSAY"),
            headers=_bearer(uid),
        )
        assert r.status_code == 422


class TestReorderQuestions:
    async def test_重排題目順序(self, client, db) -> None:
        uid = await _user(db, "ETQ_R1")
        _, qid = await _quiz(client, uid)
        a = await _add_question(client, uid, qid, stem="第一題")
        b = await _add_question(client, uid, qid, stem="第二題")
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))

        r = await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            json={"question_ids": [b["question_id"], a["question_id"]], "version": quiz.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        detail = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        assert [q["stem"] for q in detail.json()["questions"]] == ["第二題", "第一題"]

    async def test_重排不遞增題目自身版本(self, client, db) -> None:
        uid = await _user(db, "ETQ_R2")
        _, qid = await _quiz(client, uid)
        a = await _add_question(client, uid, qid)
        b = await _add_question(client, uid, qid)
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))

        await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            json={"question_ids": [b["question_id"], a["question_id"]], "version": quiz.version},
            headers=_bearer(uid),
        )
        await db.refresh(quiz)
        rows = await db.scalars(select(EtQuestion).where(EtQuestion.quiz_id == qid))
        assert all(q.version == 0 for q in rows), "題目版本不應被重排改動"
        assert quiz.version == 1, "測驗版本應遞增"

    async def test_清單缺漏被擋(self, client, db) -> None:
        uid = await _user(db, "ETQ_R3")
        _, qid = await _quiz(client, uid)
        a = await _add_question(client, uid, qid)
        await _add_question(client, uid, qid)
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))

        r = await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            json={"question_ids": [a["question_id"]], "version": quiz.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_QUESTION_004"

    async def test_重排錯誤碼與章節項目不同(self, client, db) -> None:
        """三層重排須以 error_code 區辨，否則前端無從分辨是哪一層失敗。"""
        uid = await _user(db, "ETQ_R4")
        _, qid = await _quiz(client, uid)
        await _add_question(client, uid, qid)
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == qid))
        r = await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            json={"question_ids": [], "version": quiz.version},
            headers=_bearer(uid),
        )
        assert r.json()["error_code"] not in {"ET_CHAPTER_002", "ET_ITEM_002"}


class TestDeleteQuestion:
    async def test_刪除題目連帶軟刪選項與作答明細(self, client, db) -> None:
        """作答**主檔**不刪——刪的是一題，不是整場作答。"""
        uid = await _user(db, "ETQ_D1")
        cid, qid = await _quiz(client, uid)
        question = await _add_question(client, uid, qid)
        now = utcnow()
        audit = {"created_user": uid, "created_date": now, "deleted": 0}
        attempt = EtQuizAttemptM(
            user_id="STU01",
            course_id=cid,
            quiz_id=qid,
            attempt_no=1,
            status=ATTEMPT_IN_PROGRESS,
            question_order="[]",
            option_order="[]",
            pass_score_snapshot=80,
            started_at=now,
            **audit,
        )
        db.add(attempt)
        await db.flush()
        db.add(
            EtQuizAttemptD(
                attempt_id=attempt.attempt_id,
                question_id=question["question_id"],
                stem_snapshot="題幹",
                points_snapshot=100,
                type_snapshot=QUESTION_SINGLE,
                options_snapshot="[]",
                **audit,
            )
        )
        await db.flush()

        r = await client.delete(f"/api/et/questions/{question['question_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text

        row = await db.scalar(select(EtQuestion).where(EtQuestion.question_id == question["question_id"]))
        assert row.deleted == 1
        options = list(await db.scalars(select(EtOption).where(EtOption.question_id == question["question_id"])))
        assert options and all(o.deleted == 1 for o in options)
        details = list(await db.scalars(select(EtQuizAttemptD).where(EtQuizAttemptD.attempt_id == attempt.attempt_id)))
        assert details and all(d.deleted == 1 for d in details), "作答明細應軟刪（#202 裁示，原為 hard delete）"
        await db.refresh(attempt)
        assert attempt.deleted == 0, "作答主檔不應被刪——刪的是一題，不是整場作答"

    async def test_刪除後剩餘題目順序遞補(self, client, db) -> None:
        uid = await _user(db, "ETQ_D2")
        _, qid = await _quiz(client, uid)
        ids = [(await _add_question(client, uid, qid, stem=f"第{i}題"))["question_id"] for i in range(3)]

        await client.delete(f"/api/et/questions/{ids[0]}", headers=_bearer(uid))
        detail = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
        remaining = detail.json()["questions"]
        assert [q["question_id"] for q in remaining] == ids[1:]
        assert [q["sort_order"] for q in remaining] == [1, 2]

    async def test_查無題目回_404(self, client, db) -> None:
        uid = await _user(db, "ETQ_D3")
        r = await client.delete("/api/et/questions/999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_QUESTION_001"

    async def test_非擁有者不可刪除(self, client, db) -> None:
        owner = await _user(db, "ETQ_D4")
        other = await _user(db, "ETQ_D5")
        _, qid = await _quiz(client, owner)
        question = await _add_question(client, owner, qid)
        r = await client.delete(f"/api/et/questions/{question['question_id']}", headers=_bearer(other))
        assert r.status_code == 403
