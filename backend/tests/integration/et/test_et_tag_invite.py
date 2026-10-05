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


class TestOwnerIsNeverEnrolledIntoOwnCourse:
    """#520：課程擁有者不得被標籤帶入**自己的**課程。

    ## 排除做在 `bulk_enroll_returning`——三條路徑的唯一匯流點

    | 路徑 | 呼叫端 | 本檔是否涵蓋 |
    |---|---|---|
    | 發布時依課程標籤帶入 | `course/publish_service` | ✅ 本組 |
    | 已發布課程新增標籤（`FR-ET-US8-04`）| `course/service.add_tags` | ✅ 本組 |
    | 貼標追溯（`FR-ET-US8-05`）| `roles/assign_service` | `test_et_tag_backfill.py` |

    ⚠️ **`target_user_ids` 仍然會回出擁有者**——這是刻意的。那支的語意是「掛這些標籤
    的學員有誰」，擁有者確實掛著；排除是**帶入時**的規則，不是解析時的。兩者混在一起
    會讓「他掛了這個標籤嗎」這個問題在不同呼叫端得到不同答案。
    """

    async def test_擁有者不會被帶入自己的課程(self, client, db) -> None:
        """🔴 擁有者身上有 `ET_STUDENT` 角色（建立帳號時自動授予，#89），所以他本來就在
        標籤帶入的母體裡——那正是 #520 的成因。"""
        teacher = await _user(db, "t_own10", ROLE_TEACHER)
        db.add(
            EtUserRole(
                user_id=teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_own10")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, teacher, tag_id)

        created = await _repo.bulk_enroll_returning(db, cid, [teacher], operator=OperatorInfo(user_id=teacher))

        assert created == [], "擁有者被帶入了自己的課程（#520）"
        assert await _enrolled(db, cid) == []

    async def test_同一次帶入仍把其他學員加進去(self, client, db) -> None:
        """🔴 與上一條**成對**：少了它，把 `bulk_enroll_returning` 改成「一律不加入」
        也會通過上一條，而那會讓整個標籤帶入功能靜默失效。"""
        teacher = await _user(db, "t_own11", ROLE_TEACHER)
        student = await _user(db, "s_own11")
        db.add(
            EtUserRole(
                user_id=teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, teacher)

        created = await _repo.bulk_enroll_returning(db, cid, [teacher, student], operator=OperatorInfo(user_id=teacher))

        assert created == [student], "擁有者應被濾掉、其他學員應照常加入"

    async def test_擁有者在他人課程仍可被帶入(self, client, db) -> None:
        """🔴 第三條成對斷言：排除的判準是「他是**這門課**的擁有者」，不是「他是教師」。

        教師修別人開的課是合法的。
        """
        owner = await _user(db, "t_own12", ROLE_TEACHER)
        other_teacher = await _user(db, "t_oth12", ROLE_TEACHER)
        db.add(
            EtUserRole(
                user_id=other_teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, owner)

        created = await _repo.bulk_enroll_returning(db, cid, [other_teacher], operator=OperatorInfo(user_id=owner))

        assert created == [other_teacher], "他人課程的帶入被誤擋了"
