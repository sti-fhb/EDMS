"""標籤帶入 / 貼標追溯之通知信（US8 / #273）。

#247 補上了標籤帶入本身（人真的被加進課程），但**刻意沒有寄信**——於是教師發布課程、
系統把數十位學員加進去，沒有任何人收到通知，他們得自己去「我的課程」才會發現多了一
門課。本檔釘住把那個迴圈關起來之後的行為。

## 為何一律篩 `STATUS='PENDING'` 而不看 `queued_count`

平台 `NotifyService` 的渲染失敗是靜默的：params 缺一個範本要的 key → 整批寫成
`STATUS='FAILED'`、`queued_count=0`，**且不拋錯**。若斷言「有寫入 `DP_EMAIL_LOG` 幾列」
或「呼叫沒拋錯」，一封空信也會讓測試變綠。`PENDING` 才代表**渲染成功、排進 outbox**。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag
from app.et.constants import ITEM_MATERIAL, ROLE_STUDENT, ROLE_TEACHER
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_INVITE = "COURSE_INVITE"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"姓名{user_id}",
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


async def _new_tag(db, name: str, *, is_all: bool = False) -> int:
    tag = EtTag(
        tag_name=name,
        is_active=True,
        is_all=is_all,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _tag_user(db, user_id: str, tag_id: int) -> None:
    db.add(EtUserTag(user_id=user_id, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()


async def _attach_tag(db, course_id: int, tag_id: int) -> None:
    db.add(EtCourseTag(course_id=course_id, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()


async def _publishable_course(client, db, teacher: str, *, name: str = "採血作業新進人員訓練") -> int:
    """建一門恰好滿足全部發布檢核的課程（1 章節 + 1 教材 + 1 標籤 + 起訖時間）。

    這裡掛的是一個**沒有任何人員**的標籤，讓各測試自行掛上帶人的標籤——否則基準資料
    本身就會產生收件人，寄了幾封信便說不清是哪個標籤造成的。
    """
    created = await client.post(
        _COURSES,
        json={
            "course_name": name,
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2026-09-30T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    # 標籤名以 course_id 命名——`UQ_ET_TAG_NAME` 為全域唯一，同一測試建兩門課會撞名。
    await _attach_tag(db, cid, await _new_tag(db, f"空標籤{cid}"))
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    chapter_id = ch.json()["chapter_id"]
    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert mat.status_code == 201, mat.text
    return cid


async def _pending_invites(db, template_code: str = _INVITE) -> list[DpEmailLog]:
    """排進 outbox 且**渲染成功**的通知信（見模組 docstring）。"""
    rows = await db.execute(
        select(DpEmailLog).where(
            DpEmailLog.template_code == template_code,
            DpEmailLog.module == "ET",
            DpEmailLog.status == "PENDING",
        )
    )
    return list(rows.scalars().all())


class TestPublishSendsInvites:
    """AC 2：發布時依標籤批次加入者，**每人寄一封**通知信。"""

    async def test_每位新加入的學員各收到一封(self, client, db) -> None:
        teacher = await _user(db, "tn_t01", ROLE_TEACHER)
        tag_id = await _new_tag(db, "護理師_tn01")
        students = [await _user(db, f"tn_s0{i}") for i in (1, 2, 3)]
        for s in students:
            await _tag_user(db, s, tag_id)

        cid = await _publishable_course(client, db, teacher)
        await _attach_tag(db, cid, tag_id)

        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["invited_count"] == 3

        logs = await _pending_invites(db)
        assert len(logs) == 3
        assert {log.recipient for log in logs} == {f"{s}@edms.local" for s in students}

    async def test_信件內容確實代入該收件人的姓名與課程(self, client, db) -> None:
        """渲染是否真的發生——只看有沒有列，一封空信也會過。"""
        teacher = await _user(db, "tn_t02", ROLE_TEACHER)
        tag_id = await _new_tag(db, "護理師_tn02")
        student = await _user(db, "tn_s04")
        await _tag_user(db, student, tag_id)

        cid = await _publishable_course(client, db, teacher, name="感染管制年度訓練")
        await _attach_tag(db, cid, tag_id)
        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        code = r.json()["invitation_code"]

        (log,) = await _pending_invites(db)
        assert "感染管制年度訓練" in log.subject
        assert "姓名tn_s04" in log.body
        assert "姓名tn_t02" in log.body, "應帶入課程擁有者（教師）姓名"
        assert code in log.body, "應帶入邀請碼"
        assert f"/et/courses/{cid}/learn" in log.body, "標籤帶入者已在課程中，連結直接指向學習頁"
        assert "{" not in log.body, "殘留未代入的佔位符代表 params key 對不上"

    async def test_沒有人符合標籤時不寄信(self, client, db) -> None:
        teacher = await _user(db, "tn_t03", ROLE_TEACHER)
        cid = await _publishable_course(client, db, teacher)
        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["invited_count"] == 0
        assert await _pending_invites(db) == []

    async def test_已在課程中者不重複寄信(self, client, db) -> None:
        """`bulk_enroll` 之 `ON CONFLICT DO NOTHING` 只回新增者；寄信須跟著只寄給新增者。"""
        teacher = await _user(db, "tn_t04", ROLE_TEACHER)
        tag_id = await _new_tag(db, "護理師_tn04")
        student = await _user(db, "tn_s05")
        await _tag_user(db, student, tag_id)
        cid = await _publishable_course(client, db, teacher)
        await _attach_tag(db, cid, tag_id)
        # 學員已自行以邀請碼加入（或先前已被帶入）
        db.add(
            EtEnrollment(
                user_id=student,
                course_id=cid,
                join_source="INVITATION_CODE",
                joined_at=utcnow(),
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()

        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["invited_count"] == 0
        assert await _pending_invites(db) == []

    async def test_被移除的學員不會被帶回也不會收到信(self, client, db) -> None:
        """#247 SA Q1 裁示 C：移除是教師的管理動作，標籤帶入不得把人帶回來。"""
        teacher = await _user(db, "tn_t05", ROLE_TEACHER)
        tag_id = await _new_tag(db, "護理師_tn05")
        removed = await _user(db, "tn_s06")
        await _tag_user(db, removed, tag_id)
        cid = await _publishable_course(client, db, teacher)
        await _attach_tag(db, cid, tag_id)
        db.add(
            EtEnrollment(
                user_id=removed,
                course_id=cid,
                join_source="TAG_DEFAULT",
                joined_at=utcnow(),
                completion_status="NOT_STARTED",
                is_removed=True,
                removed_at=utcnow(),
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()

        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        assert r.json()["invited_count"] == 0
        assert await _pending_invites(db) == []

        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == removed, EtEnrollment.course_id == cid)
        )
        assert row.is_removed is True, "標籤帶入不得把被移除者翻回成員"


class TestNotifyFailureDoesNotBreakPublish:
    """AC 3：寄送失敗 MUST NOT 影響已加入狀態。"""

    async def test_範本不存在時課程仍發布成功且學員仍在課程中(self, client, db, monkeypatch) -> None:
        """管理者刪掉一支範本，不該讓課程發布連同已寫入的選課列一起消失。

        `NotifyService.send_email` 對「範本不存在」拋 `AppError`；該例外若冒到 router，
        `get_db` 會 rollback 整個交易。
        """
        from app.dp.notify.service import NotifyService

        async def _boom(*_args, **_kwargs):
            raise AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001")

        teacher = await _user(db, "tn_t06", ROLE_TEACHER)
        tag_id = await _new_tag(db, "護理師_tn06")
        student = await _user(db, "tn_s07")
        await _tag_user(db, student, tag_id)
        cid = await _publishable_course(client, db, teacher)
        await _attach_tag(db, cid, tag_id)

        monkeypatch.setattr(NotifyService, "send_email", _boom)
        r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.json()["invited_count"] == 1
        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
        )
        assert row is not None, "寄信失敗不得回滾學員的加入"
        assert row.is_removed is False
