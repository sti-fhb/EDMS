"""作答紀錄依輪次分段、要求重測後結業成績只計新一輪（#709）。

`ET_QUIZ_RETRY_RESET` 原本不分「要求重測」（#361，測驗內容已改）與「重置重考次數」
（ET02，同一份測驗多給機會），兩者都只記起點。#709 新增 `RESET_KIND`：

| 種類 | 寫入端 | 分段顯示 | 最高分／平均成績 |
|---|---|---|---|
| `RETEST` | `add_retry_resets`（#361）| 「教師要求重測（測驗內容已更新）」| **只計最近一次 RETEST 之後** |
| `RETRY` | `add_retry_reset`（ET02）| 「重考次數已重置」| 所有輪次（不變）|
| `NULL` | #709 之前的舊列 | 「重新計算起點」| 所有輪次（不變）|
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.et.constants import ATTEMPT_SUBMITTED, QUESTION_SINGLE, ROLE_STUDENT
from app.et.quiz.models import EtQuestion, EtQuizAttemptD, EtQuizAttemptM, EtQuizRetryReset
from tests.integration.et.test_et_quiz_retest import (
    _bearer,
    _complete_item,
    _course_with_quiz,
    _enroll,
    _save_and_apply,
    _settings_body,
    _user,
)

pytestmark = pytest.mark.integration


async def _question(db, quiz_id: int) -> int:
    now = utcnow()
    q = EtQuestion(
        quiz_id=quiz_id,
        question_type=QUESTION_SINGLE,
        stem="題幹",
        points=100,
        sort_order=1,
        created_user="SYSTEM",
        created_date=now,
        deleted=0,
    )
    db.add(q)
    await db.flush()
    return q.question_id


async def _scored(db, *, user_id: str, course_id: int, quiz_id: int, question_id: int, no: int, score: int) -> None:
    """一次已提交的作答，**帶 100 分配分快照**——最高分以配分換算（#642），沒有明細就恆為 0。"""
    now = utcnow()
    m = EtQuizAttemptM(
        user_id=user_id,
        course_id=course_id,
        quiz_id=quiz_id,
        attempt_no=no,
        started_at=now - timedelta(minutes=10),
        submitted_at=now,
        status=ATTEMPT_SUBMITTED,
        score=Decimal(score),
        is_pass=score >= 80,
        pass_score_snapshot=80,
        time_limit_snapshot=None,
        question_order="[]",
        option_order="{}",
        created_user=user_id,
        created_date=now,
        deleted=0,
    )
    db.add(m)
    await db.flush()
    db.add(
        EtQuizAttemptD(
            attempt_id=m.attempt_id,
            question_id=question_id,
            stem_snapshot="題幹",
            points_snapshot=100,
            type_snapshot=QUESTION_SINGLE,
            options_snapshot="[]",
            score=Decimal(score),
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _setup(db, tag: str) -> dict:
    """教師的一門課＋一題測驗；一位學員第 1 次考 90 分及格並完成該項目。"""
    teacher = await _user(db, f"ZTR{tag}T")
    course_id, item_id, quiz_id = await _course_with_quiz(db, teacher)
    question_id = await _question(db, quiz_id)
    student = await _user(db, f"ZTR{tag}S", roles=(ROLE_STUDENT,))
    await _enroll(db, student, course_id)
    await _scored(db, user_id=student, course_id=course_id, quiz_id=quiz_id, question_id=question_id, no=1, score=90)
    await _complete_item(db, student, course_id, item_id)
    return {"teacher": teacher, "student": student, "cid": course_id, "qid": quiz_id, "question": question_id}


async def _require_retest(client, db, ctx) -> None:
    """勾「要求重測」存檔後按「更新」——#631 起已發布課程的重測延到套用當下才執行。"""
    body = await _settings_body(db, ctx["qid"], pass_score=85, require_retest=True)
    r = await client.put(f"/api/et/quizzes/{ctx['qid']}", json=body, headers=_bearer(ctx["teacher"]))
    await _save_and_apply(client, db, ctx["teacher"], ctx["cid"], r)


async def _kinds(db, ctx) -> list[str | None]:
    rows = await db.scalars(
        select(EtQuizRetryReset.reset_kind)
        .where(EtQuizRetryReset.user_id == ctx["student"], EtQuizRetryReset.quiz_id == ctx["qid"])
        .order_by(EtQuizRetryReset.reset_id)
    )
    return list(rows)


async def _intro(client, ctx) -> dict:
    r = await client.get(f"/api/et/quizzes/{ctx['qid']}/intro", headers=_bearer(ctx["student"]))
    assert r.status_code == 200, r.text
    return r.json()


class TestResetKindWritten:
    async def test_要求重測寫入_RETEST(self, client, db) -> None:
        ctx = await _setup(db, "01")
        await _require_retest(client, db, ctx)

        assert await _kinds(db, ctx) == ["RETEST"]

    async def test_重置重考次數寫入_RETRY(self, client, db) -> None:
        teacher = await _user(db, "ZTR02T")
        cid, _item, qid = await _course_with_quiz(db, teacher)
        question = await _question(db, qid)
        student = await _user(db, "ZTR02S", roles=(ROLE_STUDENT,))
        await _enroll(db, student, cid)
        # max_retry=2 → 本輪 3 次，全部不及格才可重置
        for no in (1, 2, 3):
            await _scored(db, user_id=student, course_id=cid, quiz_id=qid, question_id=question, no=no, score=10)

        r = await client.post(
            f"/api/et/courses/{cid}/students/{student}/quizzes/{qid}/retry-reset", headers=_bearer(teacher)
        )

        assert r.status_code == 200, r.text
        assert await _kinds(db, {"student": student, "qid": qid}) == ["RETRY"]


class TestRoundBoundaries:
    async def test_引導頁回傳輪次分界_含原因與時間(self, client, db) -> None:
        ctx = await _setup(db, "03")
        await _require_retest(client, db, ctx)

        resets = (await _intro(client, ctx))["resets"]

        assert len(resets) == 1
        assert resets[0]["after_attempt_no"] == 1
        assert resets[0]["kind"] == "RETEST"
        assert resets[0]["executed_at"]

    async def test_舊資料原因為空(self, client, db) -> None:
        ctx = await _setup(db, "04")
        now = utcnow()
        db.add(
            EtQuizRetryReset(
                course_id=ctx["cid"],
                user_id=ctx["student"],
                quiz_id=ctx["qid"],
                attempt_count_at_reset=1,
                executed_by=ctx["teacher"],
                executed_at=now,
                created_user=ctx["teacher"],
                created_date=now,
            )
        )
        await db.flush()

        resets = (await _intro(client, ctx))["resets"]

        assert [r_["kind"] for r_ in resets] == [None]

    async def test_教師端作答總覽回傳輪次分界(self, client, db) -> None:
        ctx = await _setup(db, "05")
        await _require_retest(client, db, ctx)

        r = await client.get(f"/api/et/courses/{ctx['cid']}/attempt-overview", headers=_bearer(ctx["teacher"]))

        assert r.status_code == 200, r.text
        student = next(s for s in r.json()["students"] if s["user_id"] == ctx["student"])
        quiz = next(q for q in student["quizzes"] if q["quiz_id"] == ctx["qid"])
        assert [(b["after_attempt_no"], b["kind"]) for b in quiz["resets"]] == [(1, "RETEST")]


class TestBestScoreAfterRetest:
    async def test_要求重測後尚未重考時不顯示最高分(self, client, db) -> None:
        """舊版測驗的 90 分不再代表結業成績——重測後還沒考就沒有成績。"""
        ctx = await _setup(db, "06")
        await _require_retest(client, db, ctx)

        intro = await _intro(client, ctx)

        assert intro["best_score"] is None
        assert intro["last_score"] is not None, "最近一次（舊輪）仍照實顯示"

    async def test_要求重測後最高分只計新一輪(self, client, db) -> None:
        ctx = await _setup(db, "07")
        await _require_retest(client, db, ctx)
        await _scored(
            db,
            user_id=ctx["student"],
            course_id=ctx["cid"],
            quiz_id=ctx["qid"],
            question_id=ctx["question"],
            no=2,
            score=40,
        )

        intro = await _intro(client, ctx)

        assert Decimal(intro["best_score"]) == Decimal("40.00"), "舊輪的 90 分不得計入"

    async def test_重置重考次數後最高分仍計所有輪次(self, client, db) -> None:
        teacher = await _user(db, "ZTR08T")
        cid, _item, qid = await _course_with_quiz(db, teacher)
        question = await _question(db, qid)
        student = await _user(db, "ZTR08S", roles=(ROLE_STUDENT,))
        await _enroll(db, student, cid)
        for no, score in ((1, 70), (2, 10), (3, 10)):
            await _scored(db, user_id=student, course_id=cid, quiz_id=qid, question_id=question, no=no, score=score)
        r = await client.post(
            f"/api/et/courses/{cid}/students/{student}/quizzes/{qid}/retry-reset", headers=_bearer(teacher)
        )
        assert r.status_code == 200, r.text
        await _scored(db, user_id=student, course_id=cid, quiz_id=qid, question_id=question, no=4, score=20)

        intro = await _intro(client, {"qid": qid, "student": student})

        assert Decimal(intro["best_score"]) == Decimal("70.00"), "同一份測驗多給機會，舊輪成績照算"

    async def test_ET02_平均成績只計重測後一輪(self, client, db) -> None:
        ctx = await _setup(db, "09")
        await _require_retest(client, db, ctx)
        await _scored(
            db,
            user_id=ctx["student"],
            course_id=ctx["cid"],
            quiz_id=ctx["qid"],
            question_id=ctx["question"],
            no=2,
            score=40,
        )

        r = await client.get(f"/api/et/courses/{ctx['cid']}/students", headers=_bearer(ctx["teacher"]))

        assert r.status_code == 200, r.text
        row = next(s for s in r.json()["data"] if s["user_id"] == ctx["student"])
        assert Decimal(str(row["avg_score"])) == Decimal("40.00")

    async def test_ET02_重測後尚未重考時該測驗不計入平均(self, client, db) -> None:
        """平均的分母是「已作答測驗」——重測後這一輪尚未作答，視同未作答（不是 0 分）。"""
        ctx = await _setup(db, "10")
        await _require_retest(client, db, ctx)

        r = await client.get(f"/api/et/courses/{ctx['cid']}/students", headers=_bearer(ctx["teacher"]))

        assert r.status_code == 200, r.text
        row = next(s for s in r.json()["data"] if s["user_id"] == ctx["student"])
        assert row["avg_score"] is None


async def _best_and_avg(client, ctx) -> tuple[Decimal | None, Decimal | None]:
    """同一情境下 ET07 引導頁最高分與 ET02 平均成績——兩條查詢路徑（Python／SQL）要同口徑。"""
    best = (await _intro(client, ctx))["best_score"]
    r = await client.get(f"/api/et/courses/{ctx['cid']}/students", headers=_bearer(ctx["teacher"]))
    assert r.status_code == 200, r.text
    avg = next(s for s in r.json()["data"] if s["user_id"] == ctx["student"])["avg_score"]
    return (None if best is None else Decimal(best)), (None if avg is None else Decimal(str(avg)))


async def _retry_reset(client, ctx) -> None:
    r = await client.post(
        f"/api/et/courses/{ctx['cid']}/students/{ctx['student']}/quizzes/{ctx['qid']}/retry-reset",
        headers=_bearer(ctx["teacher"]),
    )
    assert r.status_code == 200, r.text


async def _scores(db, ctx, *pairs: tuple[int, int]) -> None:
    for no, score in pairs:
        await _scored(
            db,
            user_id=ctx["student"],
            course_id=ctx["cid"],
            quiz_id=ctx["qid"],
            question_id=ctx["question"],
            no=no,
            score=score,
        )


async def _setup_failed(db, tag: str, *pairs: tuple[int, int]) -> dict:
    """同 `_setup`，但學員的作答由呼叫端指定（全部不及格的情境）。"""
    teacher = await _user(db, f"ZTR{tag}T")
    course_id, _item, quiz_id = await _course_with_quiz(db, teacher)
    question_id = await _question(db, quiz_id)
    student = await _user(db, f"ZTR{tag}S", roles=(ROLE_STUDENT,))
    await _enroll(db, student, course_id)
    ctx = {"teacher": teacher, "student": student, "cid": course_id, "qid": quiz_id, "question": question_id}
    await _scores(db, ctx, *pairs)
    return ctx


class TestRetestCoversUnpassed:
    """#709 SA 裁示：要求重測是出題疏失，所有作答過的學員都拿到同樣的新一輪，不只限已通過者。"""

    async def test_未通過學員的舊版成績不計入最高分(self, client, db) -> None:
        ctx = await _setup_failed(db, "11", (1, 50))
        await _require_retest(client, db, ctx)
        await _scores(db, ctx, (2, 40))

        assert await _kinds(db, ctx) == ["RETEST"], "未通過者也要寫入重測起點"
        assert await _best_and_avg(client, ctx) == (Decimal("40.00"), Decimal("40.00")), "舊版的 50 分不得計入"

    async def test_重置重考次數後尚未再考的學員仍被要求重測(self, client, db) -> None:
        """🔴 起點只看 RETEST：若改看任一種重置，這位學員本輪沒有作答會被排除，舊版成績照算。"""
        ctx = await _setup_failed(db, "12", (1, 70), (2, 10), (3, 10))
        await _retry_reset(client, ctx)
        await _require_retest(client, db, ctx)
        await _scores(db, ctx, (4, 30))

        assert await _kinds(db, ctx) == ["RETRY", "RETEST"]
        assert await _best_and_avg(client, ctx) == (Decimal("30.00"), Decimal("30.00")), "舊版的 70 分不得計入"


class TestResetCombinations:
    async def test_重測後再重置重考次數_最高分仍從重測起算(self, client, db) -> None:
        ctx = await _setup(db, "13")
        await _require_retest(client, db, ctx)
        await _scores(db, ctx, (2, 40), (3, 10), (4, 10))
        await _retry_reset(client, ctx)
        await _scores(db, ctx, (5, 20))

        assert await _kinds(db, ctx) == ["RETEST", "RETRY"]
        # 90 在重測前（不計）；40 在重測後、重置重考次數前（RETRY 不移動起點，照計）
        assert await _best_and_avg(client, ctx) == (Decimal("40.00"), Decimal("40.00"))

    async def test_連續兩次要求重測只計最後一次之後(self, client, db) -> None:
        ctx = await _setup(db, "14")
        await _require_retest(client, db, ctx)
        await _scores(db, ctx, (2, 85))
        await _require_retest(client, db, ctx)
        await _scores(db, ctx, (3, 50))

        assert await _kinds(db, ctx) == ["RETEST", "RETEST"]
        assert await _best_and_avg(client, ctx) == (Decimal("50.00"), Decimal("50.00"))
