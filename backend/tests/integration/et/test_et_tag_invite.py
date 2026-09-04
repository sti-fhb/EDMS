"""發布課程時依受訓單位標籤自動帶入學員（US3 FR-ET-US3-12 前半 / #247 追加）。

實測回饋：課程掛了「護理師」標籤發布出去，具該標籤的學員卻沒被帶進課程——受訓單位
標籤在發布流程裡等於沒有作用。本檔釘住補上後的行為。
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag
from app.et.constants import ROLE_STUDENT, ROLE_TEACHER, SOURCE_TAG_DEFAULT
from app.et.enrollment.tag_invite import EtTagInviteRepository
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_repo = EtTagInviteRepository()


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


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


async def _new_tag(db, name: str, *, is_all: bool = False) -> int:
    now = utcnow()
    tag = EtTag(
        tag_name=name,
        is_active=True,
        is_all=is_all,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=now,
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _tag_course(db, course_id: int, tag_id: int) -> None:
    db.add(EtCourseTag(course_id=course_id, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()


async def _tag_user(db, user_id: str, tag_id: int) -> None:
    db.add(EtUserTag(user_id=user_id, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()


async def _course(client, teacher: str, name: str = "採血作業教育") -> int:
    r = await client.post("/api/et/courses", json={"course_name": name}, headers=_bearer(teacher))
    assert r.status_code == 201, r.text
    return r.json()["course_id"]


async def _enrolled(db, course_id: int) -> list[EtEnrollment]:
    rows = await db.scalars(select(EtEnrollment).where(EtEnrollment.course_id == course_id, EtEnrollment.deleted == 0))
    return list(rows)


class TestTargetResolution:
    async def test_只帶入掛該標籤且具學員角色者(self, client, db) -> None:
        teacher = await _user(db, "t_tag01", ROLE_TEACHER)
        nurse = await _user(db, "s_tag01")
        clerk = await _user(db, "s_tag02")
        cid = await _course(client, teacher)
        nurse_tag = await _new_tag(db, "護理師_tag01")
        clerk_tag = await _new_tag(db, "行政_tag01")
        await _tag_course(db, cid, nurse_tag)
        await _tag_user(db, nurse, nurse_tag)
        await _tag_user(db, clerk, clerk_tag)

        assert await _repo.target_user_ids(db, cid) == [nurse]

    async def test_全體標籤展開為所有學員(self, client, db) -> None:
        """`IS_ALL` 不看使用者有沒有實際掛上那個標籤。

        否則「全體」就只是一個名字叫全體的普通標籤——沒有人會特地去幫每位使用者掛它。
        """
        teacher = await _user(db, "t_tag02", ROLE_TEACHER)
        a = await _user(db, "s_tag03")
        b = await _user(db, "s_tag04")
        cid = await _course(client, teacher)
        await _tag_course(db, cid, await _new_tag(db, "全體_tag02", is_all=True))

        targets = await _repo.target_user_ids(db, cid)

        assert a in targets and b in targets

    async def test_未掛標籤之課程不帶入任何人(self, client, db) -> None:
        teacher = await _user(db, "t_tag03", ROLE_TEACHER)
        await _user(db, "s_tag05")
        cid = await _course(client, teacher)

        assert await _repo.target_user_ids(db, cid) == []

    async def test_停用之學員角色不帶入(self, client, db) -> None:
        """角色指派可被管理者停用（`load_et_roles` 只取 `IS_ACTIVE=true`）。"""
        teacher = await _user(db, "t_tag04", ROLE_TEACHER)
        inactive = await _user(db, "s_tag06")
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_tag04")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, inactive, tag_id)
        await db.execute(update(EtUserRole).where(EtUserRole.user_id == inactive).values(is_active=False))
        await db.flush()

        assert await _repo.target_user_ids(db, cid) == []


class TestBulkEnroll:
    async def test_批次帶入寫入標籤來源(self, client, db) -> None:
        teacher = await _user(db, "t_tag05", ROLE_TEACHER)
        student = await _user(db, "s_tag07")
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_tag05")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, student, tag_id)

        created = await _repo.bulk_enroll(db, cid, [student], operator=OperatorInfo(user_id=teacher))

        assert created == 1
        rows = await _enrolled(db, cid)
        assert len(rows) == 1
        assert rows[0].join_source == SOURCE_TAG_DEFAULT
        assert rows[0].is_removed is False

    async def test_已在課程中者不重複建列(self, client, db) -> None:
        """課程可重複觸發（再開課、標籤異動）——`UQ_ET_ENROLLMENT_USER_COURSE` 是
        全表唯一，不 upsert 會直接撞鍵。"""
        teacher = await _user(db, "t_tag06", ROLE_TEACHER)
        student = await _user(db, "s_tag08")
        cid = await _course(client, teacher)
        op = OperatorInfo(user_id=teacher)

        assert await _repo.bulk_enroll(db, cid, [student], operator=op) == 1
        assert await _repo.bulk_enroll(db, cid, [student], operator=op) == 0

        assert len(await _enrolled(db, cid)) == 1

    async def test_被移除之學員不會被標籤帶回來(self, client, db) -> None:
        """#247 SA Q1 裁示 C 的延伸。

        若標籤帶入把 `IS_REMOVED` 翻回 false，教師移除完只要有人再發布一次就前功盡棄，
        **而且沒有任何人會發現**。要讓被移除者回來須由教師明確重新邀請（`ET-8`）。
        """
        teacher = await _user(db, "t_tag07", ROLE_TEACHER)
        student = await _user(db, "s_tag09")
        cid = await _course(client, teacher)
        op = OperatorInfo(user_id=teacher)
        await _repo.bulk_enroll(db, cid, [student], operator=op)
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
            .values(is_removed=True, removed_at=utcnow())
        )
        await db.flush()

        created = await _repo.bulk_enroll(db, cid, [student], operator=op)

        assert created == 0
        rows = await _enrolled(db, cid)
        assert len(rows) == 1
        assert rows[0].is_removed is True, "被移除狀態必須原樣保留"

    async def test_空清單不炸(self, client, db) -> None:
        teacher = await _user(db, "t_tag08", ROLE_TEACHER)
        cid = await _course(client, teacher)

        assert await _repo.bulk_enroll(db, cid, [], operator=OperatorInfo(user_id=teacher)) == 0
