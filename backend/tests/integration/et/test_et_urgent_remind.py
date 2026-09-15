"""SCHET002 截止前加急提醒（T148 / US14 / #325）。

## 對象與每週未看提醒**相反**

週提醒只寄進度 0% 者（避免長期課程的提醒疲勞）；加急提醒寄**所有未完課**者、不設進度
門檻——`spec_us14` Clarifications 明訂它是「開始後停滯者」的最後防線。

漏掉這個差異的表徵：兩種信寄給同一批人，「已經開始但還沒完成」的人在截止前完全收不到
任何提醒，而那正是最需要被提醒的一群。

## 完課與否一律即時導出

讀 `ET_ENROLLMENT.COMPLETION_STATUS` 會讓**全班**被判為未完課（那欄只在加入時寫入
`NOT_STARTED`），於是已完課的人也收到「您尚未完課」的催促信——沒有錯誤訊息，只有收信
的人覺得系統壞了。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import ITEM_MATERIAL, ROLE_STUDENT, ROLE_TEACHER, SOURCE_INVITATION_CODE
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
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


async def _course(client, db, slug: str) -> dict:
    teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
    created = await client.post(
        _COURSES,
        json={
            "course_name": f"加急課程{slug}",
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
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text
    published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, published.text
    return {"teacher": teacher, "course_id": cid, "item_id": item.json()["item_id"]}


async def _ends_in(db, course_id: int, **delta) -> None:
    await db.execute(
        update(EtCourse).where(EtCourse.course_id == course_id).values(open_end_at=utcnow() + timedelta(**delta))
    )
    await db.flush()


async def _urgent_recipients(db) -> set[str]:
    """**只取 `PENDING`**——`FAILED` 代表渲染出空信，不是寄出成功。"""
    rows = await db.scalars(
        select(DpEmailLog.recipient).where(DpEmailLog.template_code == "URGENT_REMIND", DpEmailLog.status == "PENDING")
    )
    return set(rows.all())


async def _sent_flag(db, course_id: int) -> bool:
    return await db.scalar(select(EtCourse.urgent_remind_sent).where(EtCourse.course_id == course_id))


class TestUrgentWindow:
    async def test_進入訖止前N天寄給未完課者(self, client, db) -> None:
        ctx = await _course(client, db, "u1")
        student = await _user(db, "u1_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=2)

        sent = await EtScheduleService().send_urgent_reminds(db)

        assert sent == 1
        assert await _urgent_recipients(db) == {"u1_s@edms.local"}
        assert await _sent_flag(db, ctx["course_id"]) is True

    async def test_尚未進入窗口不寄(self, client, db) -> None:
        ctx = await _course(client, db, "u2")
        student = await _user(db, "u2_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=30)

        sent = await EtScheduleService().send_urgent_reminds(db)

        assert sent == 0
        assert await _sent_flag(db, ctx["course_id"]) is False

    async def test_已到期不寄(self, client, db) -> None:
        """已逾訖止者由同一次執行的「到期關閉」處理，再寄「即將截止」是矛盾的。"""
        ctx = await _course(client, db, "u3")
        student = await _user(db, "u3_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=-1)

        sent = await EtScheduleService().send_urgent_reminds(db)

        assert sent == 0


class TestUrgentAudience:
    async def test_已完課者不寄(self, client, db) -> None:
        ctx = await _course(client, db, "u4")
        done = await _user(db, "u4_done", ROLE_STUDENT)
        undone = await _user(db, "u4_undone", ROLE_STUDENT)
        for u in (done, undone):
            await _enroll(db, user_id=u, course_id=ctx["course_id"])
        viewed = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(done))
        assert viewed.status_code == 200, viewed.text
        await _ends_in(db, ctx["course_id"], days=1)

        await EtScheduleService().send_urgent_reminds(db)

        assert await _urgent_recipients(db) == {"u4_undone@edms.local"}

    async def test_進度大於零但未完課者仍要寄(self, client, db) -> None:
        """與每週未看提醒最關鍵的差異：加急信**不設進度門檻**。漏掉會讓「已開始但停滯」
        的人在截止前完全收不到任何提醒，而那正是最需要被提醒的一群。"""
        teacher_ctx = await _course(client, db, "u5")
        cid = teacher_ctx["course_id"]
        ch = await client.post(
            f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(teacher_ctx["teacher"])
        )
        second = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "教材2"},
            headers=_bearer(teacher_ctx["teacher"]),
        )
        assert second.status_code == 201, second.text
        partial = await _user(db, "u5_partial", ROLE_STUDENT)
        await _enroll(db, user_id=partial, course_id=cid)
        viewed = await client.post(f"/api/et/items/{teacher_ctx['item_id']}/viewed", headers=_bearer(partial))
        assert viewed.status_code == 200, viewed.text
        await _ends_in(db, cid, days=1)

        await EtScheduleService().send_urgent_reminds(db)

        assert "u5_partial@edms.local" in await _urgent_recipients(db)

    async def test_已移除學員不寄(self, client, db) -> None:
        ctx = await _course(client, db, "u6")
        gone = await _user(db, "u6_gone", ROLE_STUDENT)
        await _enroll(db, user_id=gone, course_id=ctx["course_id"])
        await db.execute(update(EtEnrollment).where(EtEnrollment.user_id == gone).values(is_removed=True))
        await _ends_in(db, ctx["course_id"], days=1)

        await EtScheduleService().send_urgent_reminds(db)

        assert await _urgent_recipients(db) == set()


class TestUrgentOnlyOnce:
    async def test_次日不重寄(self, client, db) -> None:
        ctx = await _course(client, db, "u7")
        student = await _user(db, "u7_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=2)

        first = await EtScheduleService().send_urgent_reminds(db)
        second = await EtScheduleService().send_urgent_reminds(db)

        assert (first, second) == (1, 0)

    async def test_再開課後重新計(self, client, db) -> None:
        """`URGENT_REMIND_SENT` 於再開課歸零（`course/repository.mark_reopened`）——
        新時窗的加急提醒要重新算，否則延期後永遠不再提醒。"""
        ctx = await _course(client, db, "u8")
        student = await _user(db, "u8_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=2)
        await EtScheduleService().send_urgent_reminds(db)
        # 模擬再開課之歸零 + 新時窗
        await db.execute(
            update(EtCourse).where(EtCourse.course_id == ctx["course_id"]).values(urgent_remind_sent=False)
        )
        await _ends_in(db, ctx["course_id"], days=1)

        again = await EtScheduleService().send_urgent_reminds(db)

        assert again == 1

    async def test_範本停用時旗標仍置起(self, client, db) -> None:
        """範本被管理者停用不是失敗，是刻意不寄這類信。不置旗標會讓這門課每天重跑一次
        整段推導（查在籍、算完課、查收件人），而且永遠寄不出去。"""
        ctx = await _course(client, db, "u9")
        student = await _user(db, "u9_s", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await _ends_in(db, ctx["course_id"], days=2)
        await db.execute(
            update(DpNotifyTemplate)
            .where(DpNotifyTemplate.module == "ET", DpNotifyTemplate.template_code == "URGENT_REMIND")
            .values(is_enabled=False)
        )
        await db.flush()

        sent = await EtScheduleService().send_urgent_reminds(db)

        assert sent == 0
        assert await _sent_flag(db, ctx["course_id"]) is True
