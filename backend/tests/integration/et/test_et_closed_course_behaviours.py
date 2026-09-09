"""關閉後之學員端行為——跨子模組的一致性（US11 / #288）。

## 這一檔為什麼存在

關閉後的行為（唯讀回看、不可累積進度、不可作答、不可填問卷、邀請碼與邀請連結失效）
**多數已由 #255 / #273 / #274 / #279 / #284 實作**，本 issue 不改它們的判定內容。但在
#288 之前**沒有任何產品路徑能把課程設成 `CLOSED`**——那些守門條件只能由測試自己
`UPDATE ET_COURSE SET STATUS='CLOSED'` 造出狀態來驗。

也就是說：它們是以「測試造的狀態」驗過的，不是以「產品路徑造的狀態」。本檔走真實的
`POST /courses/{id}/close`，讓那些守門第一次被真實路徑觸發。

> 同一種形狀見 #284 的 `ET_SURVEY_003`（題目凍結）——#204 寫下規則，要等 #284 讓學員
> 能填答才第一次真正擋到人。

## 兩種觸發來源都驗

| 來源 | 造法 |
|---|---|
| `STATUS = CLOSED` | 走 `POST /courses/{id}/close`（本 issue 交付）|
| 閱課期間已過 | 把 `OPEN_END_AT` 改到過去（到期自動關閉屬 `ET-16`，未實作，無產品路徑）|

兩者的預期行為**完全相同**（spec 用語為「視同關閉」），故每組情境都以 `parametrize`
跑兩次——那正是 SA Q1 裁示 A 要達成的一致性，也是最容易在日後被改壞的部分：任何一處
只判 `STATUS` 的新程式碼，都會讓 `expired` 那一半變紅。

⚠️ **`attempt/` 只驗 `STATUS` 那一種**：該目錄由 #280 進行中（footprint 保護），本
issue 未替它接上期間判定，故期間已過時仍可開新作答。那個已知缺口在下方以 `xfail`
標記而非略過——`xfail` 在被修好時會變成 `XPASS` 讓 CI 變紅，於是「有人補上了」這件事
會自己浮出來；`skip` 不會。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
    SURVEY_QUESTION_SINGLE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"

#: 兩種「視同關閉」的來源。每組情境都跑兩次——兩者的預期行為完全相同。
_SOURCES = ["endpoint", "expired"]


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str) -> str:
    """建一位使用者並賦予單一 ET 角色。

    ⚠️ `EMAIL` 必須全小寫：`parse_emails` 會把教師貼進來的位址正規化為小寫再比對
    `DP_USER.EMAIL`，大寫會使「找得到帳號」的比對落空（`ET_INVITE_005`）。
    """
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


async def _tag(db, name: str) -> int:
    now = utcnow()
    tag_id = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
    if tag_id is None:
        tag = EtTag(tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=now, deleted=0)
        db.add(tag)
        await db.flush()
        tag_id = tag.tag_id
    return tag_id


async def _ready(client, db, slug: str, *, with_quiz: bool = False, with_survey: bool = False) -> dict:
    """一門已發布課程（1 章節 + 1 教材，選配小考 / 問卷）+ 一位在籍學員。

    ⚠️ 標籤刻意用課程專屬名稱、**不用「全體」**：後者會在發布時觸發標籤自動邀請，把
    全站學員角色者都加進課程並排入通知信（#273 既有行為），讓測試相依於 DB 裡有多少
    學員。此處只要一位可控的學員。
    """
    teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
    student = await _user(db, f"s_{slug}", ROLE_STUDENT)

    created = await client.post(
        _COURSES,
        json={
            "course_name": "關閉行為測試課程",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2027-09-30T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]

    tag_id = await _tag(db, f"標籤{cid}")
    db.add(EtCourseTag(course_id=cid, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]
    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert mat.status_code == 201, mat.text

    quiz_id = None
    if with_quiz:
        quiz = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_QUIZ, "title": "小考"},
            headers=_bearer(teacher),
        )
        assert quiz.status_code == 201, quiz.text
        quiz_id = quiz.json()["quiz_id"]
        question = await client.post(
            f"/api/et/quizzes/{quiz_id}/questions",
            json={
                "question_type": QUESTION_SINGLE,
                "stem": "題幹",
                "points": 100,
                "options": [{"option_text": "甲", "is_correct": True}, {"option_text": "乙", "is_correct": False}],
            },
            headers=_bearer(teacher),
        )
        assert question.status_code == 201, question.text

    survey_id = None
    if with_survey:
        survey = await client.post(
            f"{_COURSES}/{cid}/survey", json={"survey_name": "課後問卷"}, headers=_bearer(teacher)
        )
        assert survey.status_code == 201, survey.text
        survey_id = survey.json()["survey_id"]
        sq = await client.post(
            f"/api/et/surveys/{survey_id}/questions",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "滿意嗎？",
                "options": [{"option_text": "滿意"}, {"option_text": "普通"}],
            },
            headers=_bearer(teacher),
        )
        assert sq.status_code == 201, sq.text

    published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, published.text

    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=student,
            course_id=cid,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=student,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()

    return {
        "teacher": teacher,
        "student": student,
        "course_id": cid,
        "chapter_id": chapter_id,
        "item_id": mat.json()["item_id"],
        "quiz_id": quiz_id,
        "survey_id": survey_id,
        "version": published.json()["version"],
        "invitation_code": published.json()["invitation_code"],
    }


async def _apply_close(client, db, ctx: dict, source: str) -> None:
    """以指定來源讓課程「視同關閉」。

    `endpoint` 走本 issue 交付的真實路徑；`expired` 只能改 DB——到期自動轉 `CLOSED`
    屬 `ET-16`（未實作），沒有產品路徑可走。**這正是 `is_effectively_closed` 存在的
    理由**：期間過了而 `STATUS` 仍是 `PUBLISHED`，在本系統是常態而非過渡狀態。
    """
    if source == "endpoint":
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close",
            json={"version": ctx["version"]},
            headers=_bearer(ctx["teacher"]),
        )
        assert closed.status_code == 200, closed.text
        return

    now = utcnow()
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == ctx["course_id"])
        .values(open_start_at=now - timedelta(days=30), open_end_at=now - timedelta(days=1))
    )
    await db.flush()
    # 服務層是另一次查詢，但同一個 session 的 identity map 可能還握著舊的課程列。
    db.expire_all()


async def _complete_course(db, ctx: dict, *item_ids: int) -> None:
    """直接寫 `ET_PROGRESS` 讓學員完課（問卷入口與作答資格的前提）。

    走 `items/{id}/viewed` 也可以，但那支端點本身受關閉守門，且會連帶更新
    `COMPLETION_STATUS` 與 `LAST_ACTIVITY_AT`——此處只需要「完課」這個前提，
    不需要那些副作用參與被驗的行為。
    """
    now = utcnow()
    for item_id in item_ids or (ctx["item_id"],):
        db.add(
            EtProgress(
                user_id=ctx["student"],
                course_id=ctx["course_id"],
                item_id=item_id,
                is_completed=True,
                created_user=ctx["student"],
                created_date=now,
                deleted=0,
            )
        )
    await db.flush()


async def _reopen(client, ctx: dict, version: int) -> None:
    now = utcnow()
    reopened = await client.post(
        f"{_COURSES}/{ctx['course_id']}/reopen",
        json={
            "course_name": "關閉行為測試課程",
            "open_start_at": (now - timedelta(days=1)).replace(microsecond=0).isoformat(),
            "open_end_at": (now + timedelta(days=400)).replace(microsecond=0).isoformat(),
            "version": version,
        },
        headers=_bearer(ctx["teacher"]),
    )
    assert reopened.status_code == 200, reopened.text


@pytest.mark.parametrize("source", _SOURCES)
class TestLearningStaysReadable:
    """`learning/`：關閉後**唯讀回看照常**（AC 4 / #255 裁示 Q2=A）。"""

    async def test_章節與教材照常完整呈現(self, client, db, source: str) -> None:
        """⚠️ 關閉限制的是**寫入**，不是讀取。

        #255 裁示 Q2=A 明訂「讀照舊、寫全停」，依據為 Canvas 結課唯讀 / Moodle 課程
        結束日期預設不限制存取之實際做法。**不得**在此加上內容過濾——那會靜默推翻一條
        有裁示的決定，且學員的歷史紀錄會從眼前消失。
        """
        ctx = await _ready(client, db, f"lr1{source[:3]}")
        await _apply_close(client, db, ctx, source)

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert got.status_code == 200, got.text
        assert got.json()["is_closed"] is True
        assert len(got.json()["chapters"]) == 1
        assert len(got.json()["chapters"][0]["items"]) == 1, "內容不得被過濾"


@pytest.mark.parametrize("source", _SOURCES)
class TestProgressBlocked:
    """`progress/`：關閉後進度寫入一律 409 `ET_PROGRESS_001`。"""

    async def test_標記已檢視被擋(self, client, db, source: str) -> None:
        ctx = await _ready(client, db, f"pg1{source[:3]}")
        await _apply_close(client, db, ctx, source)

        got = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_PROGRESS_001"

    async def test_關閉前的進度完整保留(self, client, db, source: str) -> None:
        """關閉不摧毀任何學習紀錄——再開課後要能接續（AC 9）。"""
        ctx = await _ready(client, db, f"pg2{source[:3]}")
        viewed = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))
        assert viewed.status_code == 200, viewed.text

        await _apply_close(client, db, ctx, source)

        rows = (await db.scalars(select(EtProgress).where(EtProgress.course_id == ctx["course_id"]))).all()
        assert len(rows) == 1
        assert rows[0].is_completed is True


@pytest.mark.parametrize("source", _SOURCES)
class TestEnrollmentBlocked:
    """`enrollment/`：關閉期間邀請碼失效（AC 5 / FR-ET-US11-06）。"""

    async def test_以邀請碼加入被擋(self, client, db, source: str) -> None:
        ctx = await _ready(client, db, f"en1{source[:3]}")
        newcomer = await _user(db, f"n_en1{source[:3]}", ROLE_STUDENT)
        await _apply_close(client, db, ctx, source)

        got = await client.post(
            "/api/et/enrollments", json={"invitation_code": ctx["invitation_code"]}, headers=_bearer(newcomer)
        )

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_ENROLL_002"

    async def test_已關閉課程仍留在我的課程清單(self, client, db, source: str) -> None:
        """AC 9 / US11 FR-05：已關閉課程 MUST 仍顯示於 ET04 並標示「已關閉」。

        過濾掉會讓學員的歷史紀錄從眼前消失；卡片仍要能點進去唯讀回看。
        """
        ctx = await _ready(client, db, f"en2{source[:3]}")
        await _apply_close(client, db, ctx, source)

        got = await client.get("/api/et/my-courses", headers=_bearer(ctx["student"]))

        assert got.status_code == 200, got.text
        assert [row["course_id"] for row in got.json()["courses"]] == [ctx["course_id"]]


@pytest.mark.parametrize("source", _SOURCES)
class TestInvitationBlocked:
    """`invitation/`：關閉期間不可寄 Email 邀請（AC 5 / FR-ET-US11-07）。"""

    async def test_寄送email邀請被擋(self, client, db, source: str) -> None:
        """兩種來源給**不同的錯誤碼**——見 `rules.ensure_invitable` 的對照表。

        已關閉 → 422 `ET_INVITE_004`（僅已發布課程可邀請學員）；期間已過 → 409
        `ET_INVITE_002`（此課程目前關閉中），因為那門課的 `STATUS` 確實還是「已發布」，
        對它說「僅已發布課程可邀請」會與教師畫面上看到的狀態矛盾。
        """
        ctx = await _ready(client, db, f"iv1{source[:3]}")
        invitee = await _user(db, f"n_iv1{source[:3]}", ROLE_STUDENT)
        await _apply_close(client, db, ctx, source)

        got = await client.post(
            f"{_COURSES}/{ctx['course_id']}/invitations",
            json={"emails": f"{invitee}@edms.local"},
            headers=_bearer(ctx["teacher"]),
        )

        expected = (422, "ET_INVITE_004") if source == "endpoint" else (409, "ET_INVITE_002")
        assert (got.status_code, got.json()["error_code"]) == expected, got.text


@pytest.mark.parametrize("source", _SOURCES)
class TestSurveyBlocked:
    """`survey_fill/`：關閉後未填者不可填、已填者仍可回看（#284 AC 10 / 11）。"""

    async def _first_question(self, client, ctx: dict) -> tuple[int, int]:
        form = await client.get(f"{_COURSES}/{ctx['course_id']}/survey/form", headers=_bearer(ctx["student"]))
        assert form.status_code == 200, form.text
        question = form.json()["questions"][0]
        return question["sq_id"], question["options"][0]["so_id"]

    async def test_未填者不可填寫(self, client, db, source: str) -> None:
        ctx = await _ready(client, db, f"sv1{source[:3]}", with_survey=True)
        await _complete_course(db, ctx)
        sq_id, so_id = await self._first_question(client, ctx)
        await _apply_close(client, db, ctx, source)

        got = await client.post(
            f"{_COURSES}/{ctx['course_id']}/survey/response",
            json={"answers": [{"sq_id": sq_id, "so_id": so_id}]},
            headers=_bearer(ctx["student"]),
        )

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_SURVEY_014"

    async def test_已填者仍可唯讀回看(self, client, db, source: str) -> None:
        """#284 AC 11：關閉不影響已填者回看——`derive_entry_state` 的判定順序是
        「已填優先於課程狀態」，這條測試就是釘住那個順序。
        """
        ctx = await _ready(client, db, f"sv2{source[:3]}", with_survey=True)
        await _complete_course(db, ctx)
        sq_id, so_id = await self._first_question(client, ctx)
        submitted = await client.post(
            f"{_COURSES}/{ctx['course_id']}/survey/response",
            json={"answers": [{"sq_id": sq_id, "so_id": so_id}]},
            headers=_bearer(ctx["student"]),
        )
        assert submitted.status_code == 201, submitted.text

        await _apply_close(client, db, ctx, source)

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/survey/form", headers=_bearer(ctx["student"]))

        assert got.status_code == 200, got.text
        assert got.json()["state"] == "SUBMITTED"
        assert len(got.json()["my_answers"]) == 1

    async def test_完課未填者的側欄入口為關閉態(self, client, db, source: str) -> None:
        """入口狀態要能讓前端說出「課程已關閉，問卷已無法填寫」，而不是靜默消失。"""
        ctx = await _ready(client, db, f"sv3{source[:3]}", with_survey=True)
        await _complete_course(db, ctx)
        await _apply_close(client, db, ctx, source)

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert got.status_code == 200, got.text
        assert got.json()["survey"]["state"] == "COURSE_CLOSED"


class TestAttemptBlocked:
    """`attempt/`：關閉後不可開新作答，但**已在作答者可完成**（#279 / `spec_us6` 場景 27）。

    ⚠️ 只驗 `STATUS` 那一種來源——`attempt/` 在 #280 的 ⛔ 清單內，本 issue 未替它接上
    期間判定。期間已過的那一種以最後一條 `xfail` 標記。
    """

    async def _started(self, client, db, slug: str) -> tuple[dict, dict]:
        ctx = await _ready(client, db, slug, with_quiz=True)
        await _complete_course(db, ctx)
        started = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(ctx["student"]))
        assert started.status_code == 201, started.text
        return ctx, started.json()

    async def test_關閉後不可開新作答(self, client, db) -> None:
        ctx = await _ready(client, db, "at1", with_quiz=True)
        await _complete_course(db, ctx)
        await _apply_close(client, db, ctx, "endpoint")

        got = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(ctx["student"]))

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_ATTEMPT_006"

    async def test_關閉當下作答中的attempt仍可提交計分(self, client, db) -> None:
        """AC 3 / FR-ET-US11-04：Attempt Snapshot 讓它完成並計分。

        這是關閉**不能**做的事——把作答中的 attempt 一併中止，會讓學員剛寫完的答案
        在按下送出的那一刻消失。
        """
        ctx, attempt = await self._started(client, db, "at2")
        question = attempt["questions"][0]
        await _apply_close(client, db, ctx, "endpoint")

        saved = await client.put(
            f"/api/et/attempts/{attempt['attempt_id']}/answers/{question['question_id']}",
            json={"selected_options": [question["options"][0]["option_id"]]},
            headers=_bearer(ctx["student"]),
        )
        submitted = await client.post(
            f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=_bearer(ctx["student"])
        )

        assert saved.status_code == 204, saved.text
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["score"] is not None

    async def test_關閉後仍可查看已提交的成績(self, client, db) -> None:
        """唯讀回看涵蓋成績——關閉只停寫入（#255 裁示 Q2=A）。"""
        ctx, attempt = await self._started(client, db, "at3")
        submitted = await client.post(
            f"/api/et/attempts/{attempt['attempt_id']}/submit", headers=_bearer(ctx["student"])
        )
        assert submitted.status_code == 200, submitted.text
        await _apply_close(client, db, ctx, "endpoint")

        got = await client.get(f"/api/et/attempts/{attempt['attempt_id']}/result", headers=_bearer(ctx["student"]))

        assert got.status_code == 200, got.text

    @pytest.mark.xfail(
        reason=(
            "已知缺口（#288 刻意留下）：`attempt/` 未接上 `is_effectively_closed`，"
            "該目錄由 #280 進行中、受 footprint 保護。以 xfail 而非 skip 標記——被補上時"
            "會轉為 XPASS 讓 CI 變紅，那件事因此不需要有人記得。"
        ),
        strict=True,
    )
    async def test_期間已過亦應不可開新作答(self, client, db) -> None:
        ctx = await _ready(client, db, "at4", with_quiz=True)
        await _complete_course(db, ctx)
        await _apply_close(client, db, ctx, "expired")

        got = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(ctx["student"]))

        assert got.status_code == 409, got.text


class TestReopenRestoresEverything:
    """再開課後全部恢復（AC 9 / AC 10 / FR-ET-US11-09）。

    恢復**不需要任何額外程式碼**——各處守門都是即時判定 `STATUS` 與期間，`STATUS` 回到
    `PUBLISHED`、期間重設之後自然放行。這幾條測試釘住的正是「沒有恢復邏輯」這件事：
    若日後有人在關閉時寫下什麼需要反向清理的狀態，這裡會紅。
    """

    async def test_邀請碼沿用原碼恢復有效(self, client, db) -> None:
        """Clarifications：再開課**不重產**邀請碼。已印在講義上的碼要能繼續用。"""
        ctx = await _ready(client, db, "rr1")
        newcomer = await _user(db, "n_rr1", ROLE_STUDENT)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(ctx["teacher"])
        )
        assert closed.status_code == 200, closed.text
        blocked = await client.post(
            "/api/et/enrollments", json={"invitation_code": ctx["invitation_code"]}, headers=_bearer(newcomer)
        )
        assert blocked.status_code == 409, blocked.text

        await _reopen(client, ctx, closed.json()["version"])

        joined = await client.post(
            "/api/et/enrollments", json={"invitation_code": ctx["invitation_code"]}, headers=_bearer(newcomer)
        )

        assert joined.status_code == 201, joined.text

    async def test_再開課後可再累積進度且舊進度接續(self, client, db) -> None:
        """關閉前後的進度是同一份，不歸零（AC 9）。"""
        ctx = await _ready(client, db, "rr2", with_quiz=True)
        first = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))
        assert first.status_code == 200, first.text
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(ctx["teacher"])
        )
        assert closed.status_code == 200, closed.text
        blocked = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))
        assert blocked.status_code == 409, blocked.text

        await _reopen(client, ctx, closed.json()["version"])

        again = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))
        mine = await client.get("/api/et/my-courses", headers=_bearer(ctx["student"]))
        row = next(c for c in mine.json()["courses"] if c["course_id"] == ctx["course_id"])

        assert again.status_code == 200, again.text
        # 2 個項目（教材 + 小考）完成 1 個 → 50%；關閉期間那筆進度沒有被清掉
        assert row["progress_pct"] == 50
        assert row["status"] == "PUBLISHED"
