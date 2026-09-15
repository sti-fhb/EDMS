"""SCHET001 週統計快照（T145 / US14 / #325）。

## 母體錯了不會有任何錯誤訊息

本檔大半在驗**誰不該進統計**（草稿、未到起始、已到期、已關閉、已移除學員）。這些條件
漏掉任一個，快照照樣寫得出來、數字照樣「看起來合理」，週報也照樣寄——只是分母錯了。
故每一條都各有一個負向案例。

## 快照是 append-only

同日重跑**不覆寫**既有快照：重跑時課程資料可能已經變了，覆寫等於用今天的狀態偽造成
當時的快照。
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import COURSE_CLOSED, ITEM_MATERIAL, ROLE_STUDENT, ROLE_TEACHER, SOURCE_INVITATION_CODE
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole
from app.et.stats.models import EtWeeklyStat
from app.et.stats.service import EtStatsService

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


async def _enroll(db, *, user_id: str, course_id: int) -> None:
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


async def _course(client, db, slug: str, *, items: int = 2, publish: bool = True) -> dict:
    """一門課程（`items` 個教材項目）。

    ⚠️ 標籤用課程專屬名稱、**不用「全體」**：後者會在發布時把全站學員角色者都帶進課程，
    讓統計母體相依於 DB 裡有多少學員。
    """
    teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
    created = await client.post(
        _COURSES,
        json={
            "course_name": f"統計測試課程{slug}",
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

    item_ids = []
    for i in range(items):
        res = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_MATERIAL, "title": f"教材{i + 1}"},
            headers=_bearer(teacher),
        )
        assert res.status_code == 201, res.text
        item_ids.append(res.json()["item_id"])

    if publish:
        published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert published.status_code == 200, published.text

    return {"teacher": teacher, "course_id": cid, "item_ids": item_ids}


async def _complete(client, user_id: str, item_ids: list[int]) -> None:
    """依序完成教材項目（章節項目依序解鎖，不可跳著完成）。"""
    for item_id in item_ids:
        res = await client.post(f"/api/et/items/{item_id}/viewed", headers=_bearer(user_id))
        assert res.status_code == 200, res.text


async def _snapshot(db, course_id: int) -> EtWeeklyStat | None:
    return await db.scalar(select(EtWeeklyStat).where(EtWeeklyStat.course_id == course_id))


class TestSnapshotContent:
    async def test_每門開放中課程寫入一筆快照且內容正確(self, client, db) -> None:
        ctx = await _course(client, db, "s1", items=2)
        done = await _user(db, "st_done", ROLE_STUDENT)
        half = await _user(db, "st_half", ROLE_STUDENT)
        zero = await _user(db, "st_zero", ROLE_STUDENT)
        for u in (done, half, zero):
            await _enroll(db, user_id=u, course_id=ctx["course_id"])
        await _complete(client, done, ctx["item_ids"])
        await _complete(client, half, ctx["item_ids"][:1])

        written = await EtStatsService().take_snapshots(db)

        assert written == 1
        row = await _snapshot(db, ctx["course_id"])
        assert row is not None
        assert row.cnt_enrolled == 3
        assert (row.cnt_not_started, row.cnt_in_progress, row.cnt_completed) == (1, 1, 1)
        assert row.completion_rate == Decimal("33.33")
        # (100 + 50 + 0) / 3
        assert row.avg_progress_pct == Decimal("50.00")

    async def test_已移除學員不計入母體(self, client, db) -> None:
        """完課率的分母是「已加入**不含已移除**」。漏濾會讓數字永遠偏低，而且看起來合理。"""
        ctx = await _course(client, db, "s2", items=1)
        stay = await _user(db, "st_stay", ROLE_STUDENT)
        gone = await _user(db, "st_gone", ROLE_STUDENT)
        await _enroll(db, user_id=stay, course_id=ctx["course_id"])
        await _enroll(db, user_id=gone, course_id=ctx["course_id"])
        await _complete(client, stay, ctx["item_ids"])
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == gone, EtEnrollment.course_id == ctx["course_id"])
            .values(is_removed=True)
        )
        await db.flush()

        await EtStatsService().take_snapshots(db)

        row = await _snapshot(db, ctx["course_id"])
        assert row.cnt_enrolled == 1
        assert row.completion_rate == Decimal("100.00")

    async def test_無在籍學員仍寫快照且全為零(self, client, db) -> None:
        ctx = await _course(client, db, "s3", items=1)

        written = await EtStatsService().take_snapshots(db)

        assert written == 1
        row = await _snapshot(db, ctx["course_id"])
        assert row.cnt_enrolled == 0 and row.completion_rate == Decimal("0.00")


class TestSnapshotPopulation:
    """誰不該進統計（FR-ET-US14-01）。"""

    async def test_草稿課程不納入(self, client, db) -> None:
        ctx = await _course(client, db, "p1", publish=False)

        await EtStatsService().take_snapshots(db)

        assert await _snapshot(db, ctx["course_id"]) is None

    async def test_已關閉課程不納入(self, client, db) -> None:
        ctx = await _course(client, db, "p2")
        await db.execute(update(EtCourse).where(EtCourse.course_id == ctx["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        await EtStatsService().take_snapshots(db)

        assert await _snapshot(db, ctx["course_id"]) is None

    async def test_尚未到起始時間不納入(self, client, db) -> None:
        """漏掉這條的表徵是「全班未開始、完課率 0%」——完全像一門剛開的課，不會有人起疑。"""
        ctx = await _course(client, db, "p3")
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_start_at=utcnow() + timedelta(days=7))
        )
        await db.flush()

        await EtStatsService().take_snapshots(db)

        assert await _snapshot(db, ctx["course_id"]) is None

    async def test_已到期課程不納入(self, client, db) -> None:
        ctx = await _course(client, db, "p4")
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_end_at=utcnow() - timedelta(days=1))
        )
        await db.flush()

        await EtStatsService().take_snapshots(db)

        assert await _snapshot(db, ctx["course_id"]) is None


class TestSnapshotAppendOnly:
    async def test_同日重跑不重複寫入且不覆寫(self, client, db) -> None:
        ctx = await _course(client, db, "a1", items=1)
        student = await _user(db, "st_a1", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])

        first = await EtStatsService().take_snapshots(db)
        # 第一次之後才完成項目——若第二次覆寫，進度會變成 100
        await _complete(client, student, ctx["item_ids"])
        second = await EtStatsService().take_snapshots(db)

        assert (first, second) == (1, 0)
        rows = (await db.scalars(select(EtWeeklyStat).where(EtWeeklyStat.course_id == ctx["course_id"]))).all()
        assert len(rows) == 1
        assert rows[0].avg_progress_pct == Decimal("0.00"), "既有快照不得被重跑覆寫"


class TestPreviousSnapshot:
    async def test_首次統計無前次快照(self, client, db) -> None:
        ctx = await _course(client, db, "v1", items=1)
        await EtStatsService().take_snapshots(db)

        from app.et.stats.repository import EtStatsRepository

        previous = await EtStatsRepository().previous_avg_progress(
            db, course_id=ctx["course_id"], before=utcnow().date()
        )
        assert previous is None

    async def test_取前一筆快照而非上週同一天(self, client, db) -> None:
        """排程時點可調、也可能某週執行失敗。用日期硬算會在那種情況下比對到不存在的列，
        於是「與上週比較」永遠顯示「—」。"""
        from app.et.stats.repository import EtStatsRepository

        ctx = await _course(client, db, "v2", items=1)
        repo = EtStatsRepository()
        from decimal import Decimal

        from app.core.operator import OperatorInfo
        from app.et.stats.rules import CourseStat

        old = CourseStat(Decimal("40.00"), 1, 0, 0, Decimal("0.00"), 1)
        # 13 天前（非「上週同一天」）——仍應被取為比較基準
        await repo.insert_snapshot(
            db,
            course_id=ctx["course_id"],
            stat_date=date.today() - timedelta(days=13),
            stat=old,
            operator=OperatorInfo(user_id="SYSTEM"),
        )
        await db.flush()

        previous = await repo.previous_avg_progress(db, course_id=ctx["course_id"], before=date.today())

        assert previous == Decimal("40.00")
