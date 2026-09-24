"""ET02 測驗設定與題目整合測試（US3 / #203）。

重點在需要真 DB 才驗得了的事：

1. 測驗設定之兩態語意（`TIME_LIMIT_MIN` 空白 = 不限時、`MAX_RETRY` 0 = 不允許重考）
2. 題目與選項的全量覆寫、順序遞補
3. **刪除題目時學員作答明細之連帶軟刪除**——須先建作答測資才驗得出
4. 樂觀鎖粒度：題目重排帶測驗層 version，不動題目自身 version
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    ATTEMPT_IN_PROGRESS,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_MULTIPLE,
    QUESTION_SINGLE,
    ROLE_TEACHER,
)
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


async def _publish_course(db, course_id: int) -> None:
    """把課程直接改成「已發布且期間未過」。

    #358 M-1 起，非擁有者只能讀這種課程；發布走正式 API 要先湊齊標籤 / 起訖 / 教材
    等六項檢核，而那些與本檔要驗的授權無關，故直接改欄位。
    """
    from datetime import timedelta

    from app.core.utils import utcnow
    from app.et.constants import COURSE_PUBLISHED
    from app.et.course.models import EtCourse

    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(status=COURSE_PUBLISHED, open_end_at=utcnow() + timedelta(days=30))
    )
    await db.commit()


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

    async def test_非擁有者可讀題目但答案被遮蔽(self, client, db) -> None:
        """🔴 本測試**原本斷言 403**（#358 第 2 項）。

        `FR-ET-US7-04` 明訂他人課程可唯讀瀏覽，原行為讓教師乙點開測驗視窗只看到空白。
        但整份開放會外洩答案——原 docstring 寫的「非擁有者讀得到等於答案外洩」**仍然
        成立**，因為 `spec.md` §多重角色明訂同一人可兼具教師與學員，而 `quiz_id` 在學員
        端的學習頁拿得到。

        SA 裁示（2026-09-17）：題目可讀、答案遮蔽。
        """
        owner = await _user(db, "ETQ_S5")
        other = await _user(db, "ETQ_S6")
        cid, qid = await _quiz(client, owner)
        await client.post(f"/api/et/quizzes/{qid}/questions", json=_question_body(), headers=_bearer(owner))
        # M-1：非擁有者只能讀「已發布且期間未過」的課程
        await _publish_course(db, cid)

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(other))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answers_visible"] is False
        options = body["questions"][0]["options"]
        assert options, "題目與選項本身要讀得到"
        assert all(o["option_text"] for o in options), "選項文字不遮"
        # 🔴 遮成 None 而非 False——後者會讓畫面顯示「0 個正解」，那是錯誤資訊不是隱藏
        assert all(o["is_correct"] is None for o in options)

    async def test_非擁有者不可讀他人草稿的題庫(self, client, db) -> None:
        """#358 M-1：唯讀瀏覽的入口是 ET01「全部課程」清單，而它**不列草稿**。

        不判課程狀態的話，「清單上看不到、但用 id 直接打 API 讀得到」——`quiz/router.py`
        的檔頭原本就寫著這條顧慮（違反 `spec_us3` AC 8），角色閘只把它從「任何登入者」
        縮成「任何教師」。

        回 404 而非 403：與孤兒測驗同一個處理，不揭露「這筆存在但你看不到」。
        """
        owner = await _user(db, "ETQ_S13")
        other = await _user(db, "ETQ_S14")
        _, qid = await _quiz(client, owner)  # 未發布 ＝ 草稿

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(other))

        assert r.status_code == 404, r.text

    async def test_擁有者讀得到答案(self, client, db) -> None:
        """遮蔽只針對非擁有者——少了這條，把 `answers_visible` 寫死成 False 也會全綠。"""
        owner = await _user(db, "ETQ_S5B")
        _, qid = await _quiz(client, owner)
        await client.post(f"/api/et/quizzes/{qid}/questions", json=_question_body(), headers=_bearer(owner))

        r = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(owner))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answers_visible"] is True
        options = body["questions"][0]["options"]
        assert any(o["is_correct"] is True for o in options)

    async def test_非擁有者不可更新測驗設定(self, client, db) -> None:
        """讀放寬之後，六支寫入路徑**每一支**都要有非擁有者測試。

        本 PR 把 `get_detail` 從 `_require_owned` 改成 `_resolve_quiz`（只驗存在）。
        若日後有人比照那個改法把寫入路徑也換過去——看起來像一致性修正——沒有測試會紅，
        而那等於開放所有教師改別人的測驗。

        對照組是 material 側：`update` 與 `upload_video` 兩支寫入都有覆蓋。測驗側原本
        只有 `delete_question` 有，本 PR 把其餘五支補齊。
        """
        owner = await _user(db, "ETQ_S7")
        other = await _user(db, "ETQ_S8")
        _, qid = await _quiz(client, owner)

        r = await client.put(
            f"/api/et/quizzes/{qid}",
            headers=_bearer(other),
            json={
                "quiz_name": "被別人改的名字",
                "description": None,
                "pass_score": 60,
                "time_limit_min": None,
                "max_retry": 0,
                "version": 0,
            },
        )

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_非擁有者不可更新題目(self, client, db) -> None:
        owner = await _user(db, "ETQ_S9")
        other = await _user(db, "ETQ_S10")
        _, qid = await _quiz(client, owner)
        question = await _add_question(client, owner, qid)

        r = await client.put(
            f"/api/et/questions/{question['question_id']}",
            headers=_bearer(other),
            json={**_question_body(stem="被別人改的題幹"), "version": question["version"]},
        )

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_非擁有者不可重排題目(self, client, db) -> None:
        owner = await _user(db, "ETQ_S11")
        other = await _user(db, "ETQ_S12")
        _, qid = await _quiz(client, owner)
        first = await _add_question(client, owner, qid)

        r = await client.put(
            f"/api/et/quizzes/{qid}/questions/order",
            headers=_bearer(other),
            # ⚠️ 必須送合法 body：Pydantic 驗證**先於**授權判定，少了 `version` 會拿到
            # 422 而不是 403——那樣這條測試就驗不到它要驗的東西。
            json={"question_ids": [first["question_id"]], "version": 0},
        )

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_非擁有者不可寫入題目(self, client, db) -> None:
        """讀放寬了，寫**沒有**。少了這條，日後把 `add_question` 也改成 `_resolve_quiz`
        （看起來像一致性修正）不會有任何測試變紅，而那等於開放所有教師改別人的題庫。
        """
        owner = await _user(db, "ETQ_S5C")
        other = await _user(db, "ETQ_S6C")
        _, qid = await _quiz(client, owner)

        r = await client.post(
            f"/api/et/quizzes/{qid}/questions",
            headers=_bearer(other),
            json={
                "question_type": "SINGLE",
                "stem": "別人加的題目",
                "points": 10,
                "options": [
                    {"option_text": "A", "is_correct": True},
                    {"option_text": "B", "is_correct": False},
                ],
            },
        )

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

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
    async def test_刪除題目軟刪選項但不動學員作答明細(self, client, db) -> None:
        """**2026-09-04 / #279 SA 裁示 Q2 = C 起，作答明細不再連帶軟刪除。**

        #202 曾加上連帶軟刪除，目的是「不要**硬**刪掉學員資料」（原 spec 為 hard
        delete）。但其代價清單只涵蓋 #5 / #9 / #14 三張統計型 issue，**沒有列入 US6 的
        「學員回看自己那次考卷」**——照原本的連帶做下去，學員會看到「總分 75、明細只
        列 4 題加起來 60」這種自己對不起來的成績單。

        作答**主檔**同樣不刪——刪的是一題，不是整場作答。
        """
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
        assert details and all(d.deleted == 0 for d in details), (
            "作答明細**不得**被連帶軟刪除——`ET_QUIZ_ATTEMPT_D` 自給自足（四個快照欄位"
            "足以渲染明細），題目被刪對它沒有影響（#279 裁示 Q2 = C）"
        )
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


# ── #410：已發布課程的測驗不得被刪到 0 題 ────────────────────


async def test_已發布課程刪最後一題被擋(db, client):
    """🔴 發布檢核是**一次性**的，`evaluate_publish` 全專案只有一個呼叫點（`publish_service._blockers`），
    `publish` 與 `reopen` 共用——之後教師怎麼改都不會再被檢核到。#410 就是那個時間差。

    後果不是「發布出一個 0 題測驗」，是**發布後才被刪成 0 題**：
    `attempt/service.start` 對 0 題測驗回 404（建零題 attempt 會白吃一次次數），該項目
    因此永遠拿不到 `IS_COMPLETED`，而完課要求每一項皆完成 → **整門課永遠無法完課**，
    連帶課後問卷入口（US13 AC 1）與線下核可（US16）都拿不到。教師端則完全沒有訊號。
    """
    uid = await _user(db, "q410a")
    cid, qid = await _quiz(client, uid)
    q = await _add_question(client, uid, qid)
    await _publish_course(db, cid)

    r = await client.delete(f"/api/et/questions/{q['question_id']}", headers=_bearer(uid))

    assert r.status_code == 409, r.text
    assert r.json()["error_code"] == "ET_QUESTION_005"
    # 題目必須還在——擋下來卻已經刪掉等於沒擋
    left = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
    assert len(left.json()["questions"]) == 1


async def test_已發布課程刪非最後一題照常(db, client):
    """回歸護欄：守門只擋「刪到 0 題」，不是禁止已發布課程刪題。"""
    uid = await _user(db, "q410b")
    cid, qid = await _quiz(client, uid)
    q1 = await _add_question(client, uid, qid, points=50)
    await _add_question(client, uid, qid, points=50)
    await _publish_course(db, cid)

    r = await client.delete(f"/api/et/questions/{q1['question_id']}", headers=_bearer(uid))

    assert r.status_code == 204, r.text
    left = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
    assert len(left.json()["questions"]) == 1


async def test_草稿課程刪最後一題照常(db, client):
    """⚠️ 草稿**不受此限**——教師逐題建立時必然經過 0 題的狀態（AC 2）。

    把守門套成「一律不許刪到 0 題」會讓「建了一題又想換掉」變成做不到。
    """
    uid = await _user(db, "q410c")
    _, qid = await _quiz(client, uid)  # 不發布
    q = await _add_question(client, uid, qid)

    r = await client.delete(f"/api/et/questions/{q['question_id']}", headers=_bearer(uid))

    assert r.status_code == 204, r.text
    left = await client.get(f"/api/et/quizzes/{qid}", headers=_bearer(uid))
    assert left.json()["questions"] == []


async def test_已關閉課程刪最後一題不受限(db, client):
    """⚠️ 守門範圍是「已發布**且**學員仍可作答」——`is_effectively_closed` 的課程學員
    本來就不能作答，0 題測驗傷不到任何人，不需納入（issue 注意事項明列）。
    """
    from datetime import timedelta

    from app.et.constants import COURSE_PUBLISHED
    from app.et.course.models import EtCourse

    uid = await _user(db, "q410d")
    cid, qid = await _quiz(client, uid)
    q = await _add_question(client, uid, qid)
    # 已發布但閱課期間已過 → is_effectively_closed
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == cid)
        .values(status=COURSE_PUBLISHED, open_end_at=utcnow() - timedelta(days=1))
    )
    await db.flush()

    r = await client.delete(f"/api/et/questions/{q['question_id']}", headers=_bearer(uid))

    assert r.status_code == 204, r.text


async def test_課程詳細頁帶出題數且教材為_None(db, client):
    """#410 AC 3：教師端要看得出哪些測驗是 0 題。

    🔴 **`0` 與 `None` 不可合併**：教材項目的 `QUIZ_ID` 是 NULL，題數子查詢對它同樣
    得到 0。少一道「非測驗換成 `None`」，**每一個教材項目都會被標成 0 題異常**——
    而那種錯 CI 會全綠（型別對、數字也對，只是意思反了）。

    本條同時釘住三種狀態：教材（`None`）、零題測驗（`0`）、有題目的測驗（`1`）。
    """
    uid = await _user(db, "q410e")
    created = await client.post(_COURSES, json={"course_name": "題數"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    chapter_id = ch.json()["chapter_id"]
    for item_type, title in ((ITEM_MATERIAL, "講義"), (ITEM_QUIZ, "零題小考"), (ITEM_QUIZ, "有題小考")):
        r = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": item_type, "title": title},
            headers=_bearer(uid),
        )
        assert r.status_code == 201, r.text
        if title == "有題小考":
            await _add_question(client, uid, r.json()["quiz_id"])

    detail = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))

    by_title = {i["title"]: i["question_count"] for i in detail.json()["chapters"][0]["items"]}
    assert by_title == {"講義": None, "零題小考": 0, "有題小考": 1}
