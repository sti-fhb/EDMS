"""SCHET002 每日課程時窗檢查：到期自動關閉 + 結清逾期未提交之 attempt（US14 / #325、#317）。

## 這一檔驗的兩件事是同一個因果

到期自動關閉（T139）本身是 US14 的一條 AC，但它同時是 **#317 的修復前提**：

在它存在之前，「閱課期間已過而 `STATUS` 仍是 `PUBLISHED`」是**常態**（沒有任何東西會
把狀態推到 `CLOSED`）。於是 `spec_us6` 場景 27 那條「關閉當下已在作答者仍可完成並計分」
的窄縫，在時間軸上沒有上界——學員只要在訖止前按一次「開始作答」然後放著，就能在課程
結束後任意久回來作答、計分、寫進度。不限時測驗（`TIME_LIMIT_MIN` 為 `NULL`）更寬，連
`is_timed_out` 那道擋板都恆為 `False`。

本 job 每日執行，於是那條縫的上界收斂為「關閉後到下一次排程」。

## 結清 ≠ 沒收

結清標 `TIMEOUT` 但**照常閱卷**，比照 `spec_us6` 場景 10 的逾時自動提交——學員寫到哪
就算到哪，及格照樣回寫項目完成。沒收考卷不在場景 27 的授權範圍內。

因此 #313 的兩條測試不受影響：它們是「關閉當下立即提交」，根本不經過本 job。

## 為何掃「所有視同關閉」而非「本次剛關的」

只在關閉當下結清的話，教師**手動**按下關閉的課程（#317 原本的觸發情境、也是 #313 之前
唯一的觸發情境）永遠掃不到。故每次執行都掃 `STATUS='CLOSED'` 或「已發布但期間已過」
兩種來源——與 `is_effectively_closed` 同一組條件。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    ATTEMPT_IN_PROGRESS,
    ATTEMPT_SUBMITTED,
    ATTEMPT_TIMEOUT,
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtChapter, EtCourse
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.quiz.models import EtQuizAttemptM
from app.et.roles.models import EtUserRole
from app.et.schedules.service import EtScheduleService

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str) -> str:
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


async def _course(client, db, slug: str, *, time_limit_min: int | None = 30, quiz_first: bool = False) -> dict:
    """一門已發布課程（1 教材 + 1 小考）+ 一位在籍學員。

    ⚠️ 標籤用課程專屬名稱、**不用「全體」**：後者會在發布時把全站學員角色者都帶進課程
    並排入通知信，讓測試相依於 DB 裡有多少學員。

    Args:
        quiz_first: 測驗排在教材**之前**。解鎖判定對擁有者一樣適用（`_locked_ids` 不看
            是不是教師），而教師預覽時 `mark_item_viewed` 走 `_PreviewOnly` 分支、不寫
            `ET_PROGRESS`，於是**教師永遠解不開非第一項的測驗**。要造出「教師預覽 attempt」
            就只能讓測驗是第一項。
    """
    teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
    student = await _user(db, f"s_{slug}", ROLE_STUDENT)

    created = await client.post(
        _COURSES,
        json={
            "course_name": f"排程測試課程{slug}",
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

    async def _add_material():
        res = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_MATERIAL, "title": "教材"},
            headers=_bearer(teacher),
        )
        assert res.status_code == 201, res.text
        return res

    async def _add_quiz():
        res = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_QUIZ, "title": "小考", "time_limit_min": time_limit_min},
            headers=_bearer(teacher),
        )
        assert res.status_code == 201, res.text
        return res

    if quiz_first:
        quiz = await _add_quiz()
        mat = await _add_material()
    else:
        mat = await _add_material()
        quiz = await _add_quiz()
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
        "item_id": mat.json()["item_id"],
        "quiz_item_id": quiz.json()["item_id"],
        "quiz_id": quiz_id,
        "question_id": question.json()["question_id"],
    }


async def _expire(db, course_id: int, **ago) -> None:
    """把閱課期間推到過去（`STATUS` 仍為 `PUBLISHED`——這正是 #317 描述的常態）。

    預設推到 **2 天前**，明確越過 `SETTLE_GRACE_HOURS`（24 小時）的寬限期；要驗「寬限期
    內不結清」的案例請自行傳入較短的 `ago`（如 `minutes=1`）。
    """
    delta = timedelta(**ago) if ago else timedelta(days=2)
    await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(open_end_at=utcnow() - delta))
    await db.flush()


async def _start_attempt(client, ctx: dict) -> int:
    """學員開始作答。

    ⚠️ 必須**先完成前一個教材項目**：章節項目依序解鎖，測驗是第 2 項，前面沒完成時
    「開始作答」回 404（守門 3，見 `attempt/service` 開頭）——那個 404 看起來像「測驗
    不存在」，很容易被誤讀成 fixture 建錯。
    """
    viewed = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))
    assert viewed.status_code == 200, viewed.text
    started = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(ctx["student"]))
    assert started.status_code == 201, started.text
    return started.json()["attempt_id"]


async def _answer(client, ctx: dict, attempt_id: int, *, correct: bool) -> None:
    state = await client.get(f"/api/et/attempts/{attempt_id}", headers=_bearer(ctx["student"]))
    assert state.status_code == 200, state.text
    options = state.json()["questions"][0]["options"]
    # 選項順序於開始作答時洗牌並凍結，故以快照回傳的順序定位，不假設 index
    chosen = [o["option_id"] for o in options if (o["text"] == "甲") == correct][0]
    saved = await client.put(
        f"/api/et/attempts/{attempt_id}/answers/{ctx['question_id']}",
        json={"selected_options": [chosen]},
        headers=_bearer(ctx["student"]),
    )
    assert saved.status_code == 204, saved.text


async def _status_of(db, course_id: int) -> str:
    return await db.scalar(select(EtCourse.status).where(EtCourse.course_id == course_id))


async def _attempt(db, attempt_id: int) -> EtQuizAttemptM:
    return await db.scalar(select(EtQuizAttemptM).where(EtQuizAttemptM.attempt_id == attempt_id))


class TestCloseExpired:
    """到期自動關閉（AC 7 前半 / T139 / FR-ET-US14-06）。"""

    async def test_逾期課程自動轉關閉(self, client, db) -> None:
        ctx = await _course(client, db, "exp1")
        await _expire(db, ctx["course_id"])

        closed = await EtScheduleService().close_expired_courses(db)

        assert closed == 1
        assert await _status_of(db, ctx["course_id"]) == COURSE_CLOSED

    async def test_關閉時寫入關閉時間(self, client, db) -> None:
        ctx = await _course(client, db, "exp2")
        await _expire(db, ctx["course_id"])

        await EtScheduleService().close_expired_courses(db)

        closed_at = await db.scalar(select(EtCourse.closed_at).where(EtCourse.course_id == ctx["course_id"]))
        assert closed_at is not None

    async def test_未逾期課程不動(self, client, db) -> None:
        ctx = await _course(client, db, "exp3")

        closed = await EtScheduleService().close_expired_courses(db)

        assert closed == 0
        assert await _status_of(db, ctx["course_id"]) == COURSE_PUBLISHED

    async def test_已關閉課程不重複處理(self, client, db) -> None:
        """第二次執行不該再把同一門課算進去——否則每日都會覆寫 `CLOSED_AT`。"""
        ctx = await _course(client, db, "exp4")
        await _expire(db, ctx["course_id"])
        await EtScheduleService().close_expired_courses(db)
        first_closed_at = await db.scalar(select(EtCourse.closed_at).where(EtCourse.course_id == ctx["course_id"]))

        second = await EtScheduleService().close_expired_courses(db)

        assert second == 0
        assert (
            await db.scalar(select(EtCourse.closed_at).where(EtCourse.course_id == ctx["course_id"])) == first_closed_at
        )


class TestSettleStaleAttempts:
    """結清逾期未提交之 attempt（#317）。"""

    async def test_逾期課程之作答中attempt被結清並計分(self, client, db) -> None:
        ctx = await _course(client, db, "stl1")
        attempt_id = await _start_attempt(client, ctx)
        await _answer(client, ctx, attempt_id, correct=True)
        await _expire(db, ctx["course_id"])

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 1
        row = await _attempt(db, attempt_id)
        assert row.status == ATTEMPT_TIMEOUT
        assert row.submitted_at is not None
        # 結清是計分不是沒收：學員已作答的內容照常閱卷
        assert row.score == 100
        assert row.is_pass is True

    async def test_未作答者結清為零分且不及格(self, client, db) -> None:
        ctx = await _course(client, db, "stl2")
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"])

        await EtScheduleService().settle_stale_attempts(db)

        row = await _attempt(db, attempt_id)
        assert row.status == ATTEMPT_TIMEOUT
        assert row.score == 0
        assert row.is_pass is False

    async def test_不限時測驗亦被結清(self, client, db) -> None:
        """本缺口最寬的一側：`TIME_LIMIT_MIN` 為 `NULL` 時 `is_timed_out` 恆為 `False`，
        連 `save_answer` 的逾時擋板都不存在。"""
        ctx = await _course(client, db, "stl3", time_limit_min=None)
        attempt_id = await _start_attempt(client, ctx)
        await _answer(client, ctx, attempt_id, correct=True)
        await _expire(db, ctx["course_id"])

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 1
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_TIMEOUT

    async def test_結清後及格者項目完成已回寫(self, client, db) -> None:
        """及格回寫是計分的一部分（`spec_us6` 場景 27），結清路徑不該少做這一半。"""
        ctx = await _course(client, db, "stl4")
        attempt_id = await _start_attempt(client, ctx)
        await _answer(client, ctx, attempt_id, correct=True)
        await _expire(db, ctx["course_id"])

        await EtScheduleService().settle_stale_attempts(db)

        completed = await db.scalar(
            select(EtProgress.is_completed).where(
                EtProgress.user_id == ctx["student"],
                EtProgress.item_id == ctx["quiz_item_id"],
                EtProgress.deleted == 0,
            )
        )
        assert completed is True

    async def test_未及格者不回寫項目完成(self, client, db) -> None:
        ctx = await _course(client, db, "stl5")
        attempt_id = await _start_attempt(client, ctx)
        await _answer(client, ctx, attempt_id, correct=False)
        await _expire(db, ctx["course_id"])

        await EtScheduleService().settle_stale_attempts(db)

        completed = await db.scalar(
            select(EtProgress.is_completed).where(
                EtProgress.user_id == ctx["student"],
                EtProgress.item_id == ctx["quiz_item_id"],
                EtProgress.deleted == 0,
            )
        )
        assert completed is not True

    async def test_未逾期課程之作答中attempt不動(self, client, db) -> None:
        ctx = await _course(client, db, "stl6")
        attempt_id = await _start_attempt(client, ctx)

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_IN_PROGRESS

    async def test_手動關閉課程之殘留attempt亦被結清(self, client, db) -> None:
        """#317 原本的觸發情境——教師手動按關閉。只在「本次剛到期」時結清會永遠掃不到它。"""
        ctx = await _course(client, db, "stl7")
        attempt_id = await _start_attempt(client, ctx)
        await db.execute(update(EtCourse).where(EtCourse.course_id == ctx["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 1
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_TIMEOUT

    async def test_已提交的attempt不被重複處理(self, client, db) -> None:
        ctx = await _course(client, db, "stl8")
        attempt_id = await _start_attempt(client, ctx)
        await _answer(client, ctx, attempt_id, correct=True)
        submitted = await client.post(f"/api/et/attempts/{attempt_id}/submit", headers=_bearer(ctx["student"]))
        assert submitted.status_code == 200, submitted.text
        await _expire(db, ctx["course_id"])

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_SUBMITTED

    async def test_結清以SYSTEM為操作者(self, client, db) -> None:
        """排程沒有登入者。記成學員本人會讓稽核看起來像「他自己提交的」。"""
        ctx = await _course(client, db, "stl9")
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"])

        await EtScheduleService().settle_stale_attempts(db)

        assert (await _attempt(db, attempt_id)).updated_user == "SYSTEM"

    async def test_教師預覽之attempt結清後不寫入進度(self, client, db) -> None:
        """教師可對自己課程開 attempt 而**不必在籍**（`ensure_can_access(enrolled, is_owner)`）。

        #255 裁示 Q1 明訂教師預覽不得寫入 `ET_PROGRESS`——否則教師預覽完就出現在自己
        課程的完課統計裡。`AttemptService.submit()` 以 `_is_preview` 擋下；結清路徑繞過了
        那支 Service，若不自行補上同一道判定，一筆被遺忘的預覽 attempt 就會在課程關閉後
        由排程悄悄寫進進度表，且沒有任何錯誤訊息。
        """
        # 測驗須為章節第一項：解鎖判定對擁有者一樣適用，而教師「看教材」走
        # `_PreviewOnly` 分支不寫進度，故永遠解不開排在教材之後的測驗
        ctx = await _course(client, db, "stlp", quiz_first=True)
        teacher = ctx["teacher"]
        started = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(teacher))
        assert started.status_code == 201, started.text
        attempt_id = started.json()["attempt_id"]
        state = await client.get(f"/api/et/attempts/{attempt_id}", headers=_bearer(teacher))
        chosen = [o["option_id"] for o in state.json()["questions"][0]["options"] if o["text"] == "甲"][0]
        saved = await client.put(
            f"/api/et/attempts/{attempt_id}/answers/{ctx['question_id']}",
            json={"selected_options": [chosen]},
            headers=_bearer(teacher),
        )
        assert saved.status_code == 204, saved.text
        await _expire(db, ctx["course_id"])

        await EtScheduleService().settle_stale_attempts(db)

        row = await _attempt(db, attempt_id)
        # 考卷照常結清計分（`ET_QUIZ_ATTEMPT_M` 的列本來就會產生，那是預覽的用途）
        assert row.status == ATTEMPT_TIMEOUT
        assert row.is_pass is True
        # 但**不得**寫進度——這正是 #255 裁示 Q1 要避開的後果
        progress = await db.scalar(
            select(EtProgress.progress_id).where(
                EtProgress.user_id == teacher,
                EtProgress.item_id == ctx["quiz_item_id"],
                EtProgress.deleted == 0,
            )
        )
        assert progress is None

    async def test_軟刪除章節下的attempt不被結清(self, client, db) -> None:
        """教師刪掉整章後，那些 attempt 的考卷已無對應題目，結清它們沒有意義。"""
        ctx = await _course(client, db, "stld")
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"])
        await db.execute(update(EtChapter).where(EtChapter.course_id == ctx["course_id"]).values(deleted=1))
        await db.flush()

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_IN_PROGRESS


class TestSettleTiming:
    """何時**還不可以**結清——`spec_us6` 場景 27 的保障不得被本作業推翻（Security H-1）。"""

    async def test_課程剛到期而作答時限未到則不結清(self, client, db) -> None:
        """學員 07:30 開始 60 分鐘測驗、課程 08:00 到期、排程 08:00 執行——他還有 30 分鐘
        合法時間。若課程一關就結清，這份考卷會被強制交出並記為「逾時」，與事實不符。"""
        ctx = await _course(client, db, "grc1", time_limit_min=60)
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"], minutes=1)

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_IN_PROGRESS

    async def test_不限時測驗於寬限期內不結清(self, client, db) -> None:
        ctx = await _course(client, db, "grc2", time_limit_min=None)
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"], minutes=1)

        settled = await EtScheduleService().settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_IN_PROGRESS

    async def test_掃描後課程被再開課則不結清(self, client, db) -> None:
        """掃描與寫入之間教師按了再開課。沿用掃描結果會把一門已重新開放的課程裡、
        學員**正在寫**的考卷結清掉。

        以 stub 掃描器重現「掃描時已到期、寫入前已再開課」的時序——真實批次中這個窗口
        等於整批的執行時間。
        """
        ctx = await _course(client, db, "grc3")
        attempt_id = await _start_attempt(client, ctx)
        await _expire(db, ctx["course_id"])
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_end_at=utcnow() + timedelta(days=30))
        )
        await db.flush()

        class _StaleScan:
            async def expired_published_course_ids(self, db_, now):
                return []

            async def stale_in_progress_attempt_ids(self, db_, now):
                return [attempt_id]

        settled = await EtScheduleService(repository=_StaleScan()).settle_stale_attempts(db)

        assert settled == 0
        assert (await _attempt(db, attempt_id)).status == ATTEMPT_IN_PROGRESS


class TestCloseAudit:
    """到期自動關閉之稽核（與教師手動關閉對等）。"""

    async def test_到期關閉寫入稽核(self, client, db) -> None:
        """關閉一門課會立刻影響全部在籍學員。手動關閉有稽核、自動關閉沒有的話，
        事後查「這門課為什麼關了」會在自動關閉的案例上一無所獲。"""
        ctx = await _course(client, db, "aud1")
        await _expire(db, ctx["course_id"])

        await EtScheduleService().close_expired_courses(db)

        # 同一課程的 `ET-COURSE` 稽核還有發布那筆（operator 是教師），故以 SYSTEM 定位
        log = await db.scalar(
            select(DpAuditLog).where(
                DpAuditLog.func_name == "ET-COURSE",
                DpAuditLog.target_id == str(ctx["course_id"]),
                DpAuditLog.created_user == "SYSTEM",
            )
        )
        assert log is not None
        assert "自動關閉" in log.description
        # 排程沒有請求來源，硬填會讓該欄位變成不可信
        assert log.source_ip is None
