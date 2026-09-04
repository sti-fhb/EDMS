"""貼標追溯：新增「人 × 標籤」時補加入課程並寄彙整信（US8 / #273）。

`EtAssignService` 是 `ET_USER_ROLE` / `ET_USER_TAG` 的權威寫入口，由平台 DP 後台
「權限管理」經 `EtAssignProvider` 呼叫。#185 當時在該處留了
`TODO(ET Issue #2 / #8)`——貼標追溯依賴課程 / 選課 / 通知服務，Foundation 階段沒有。
本檔釘住補上後的行為。

直接呼叫 service 而非走 DP 端點：本功能的觸發點在 ET 這一側，經 DP 後台繞一圈只會
讓失敗訊息指向 DP 的權限層，看不出 ET 的行為對不對（比照 `test_et_tag_invite.py`）。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_TAG_DEFAULT,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.assign_service import EtAssignService
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_DIGEST = "COURSE_INVITE_DIGEST"
_INVITE = "COURSE_INVITE"
_ADMIN = "admin01"

_service = EtAssignService()


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


async def _tag(db, name: str) -> int:
    tag = EtTag(
        tag_name=name,
        is_active=True,
        is_all=False,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _course(db, owner: str, name: str, tag_id: int, *, status: str = COURSE_PUBLISHED) -> int:
    """直接落庫建課程——本檔驗的是貼標追溯，不需要走完整的發布檢核。"""
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        open_start_at=now,
        open_end_at=now,
        owner_id=owner,
        invitation_code=None,
        urgent_remind_sent=False,
        version=0,
        require_approval=False,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    db.add(EtCourseTag(course_id=course.course_id, tag_id=tag_id, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()
    return course.course_id


async def _mails(db, template_code: str) -> list[DpEmailLog]:
    """渲染成功並排入 outbox 者（`FAILED` 代表 params 對不上範本佔位）。"""
    rows = await db.execute(
        select(DpEmailLog).where(
            DpEmailLog.template_code == template_code,
            DpEmailLog.module == "ET",
            DpEmailLog.status == "PENDING",
        )
    )
    return list(rows.scalars().all())


async def _enrolled_course_ids(db, user_id: str) -> list[int]:
    rows = await db.execute(
        select(EtEnrollment.course_id).where(EtEnrollment.user_id == user_id, EtEnrollment.is_removed.is_(False))
    )
    return sorted(rows.scalars().all())


class TestTagBackfill:
    """AC 4：新增人×標籤 → 補加入該標籤之所有已發布未關閉課程 → 寄**彙整一封**。"""

    async def test_兩門課補加入但只寄一封彙整信(self, db) -> None:
        teacher = await _user(db, "bf_t01", ROLE_TEACHER)
        student = await _user(db, "bf_s01")
        tag_id = await _tag(db, "護理師_bf01")
        c1 = await _course(db, teacher, "採血作業新進人員訓練", tag_id)
        c2 = await _course(db, teacher, "感染管制年度訓練", tag_id)

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        assert await _enrolled_course_ids(db, student) == sorted([c1, c2])
        digests = await _mails(db, _DIGEST)
        assert len(digests) == 1, "多門課須彙整為一封，不可逐課一封"
        assert digests[0].recipient == f"{student}@edms.local"
        assert await _mails(db, _INVITE) == [], "貼標追溯用彙整範本，不寄逐課邀請信"

    async def test_彙整信列出每一門新加入的課程(self, db) -> None:
        teacher = await _user(db, "bf_t02", ROLE_TEACHER)
        student = await _user(db, "bf_s02")
        tag_id = await _tag(db, "護理師_bf02")
        c1 = await _course(db, teacher, "採血作業新進人員訓練", tag_id)
        c2 = await _course(db, teacher, "感染管制年度訓練", tag_id)

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        (digest,) = await _mails(db, _DIGEST)
        assert "姓名bf_s02" in digest.body
        assert "採血作業新進人員訓練" in digest.body
        assert "感染管制年度訓練" in digest.body
        assert f"/et/courses/{c1}/learn" in digest.body
        assert f"/et/courses/{c2}/learn" in digest.body
        assert "{" not in digest.body, "殘留未代入的佔位符代表 params key 對不上"

    async def test_加入來源記為標籤帶入(self, db) -> None:
        teacher = await _user(db, "bf_t03", ROLE_TEACHER)
        student = await _user(db, "bf_s03")
        tag_id = await _tag(db, "護理師_bf03")
        await _course(db, teacher, "採血作業", tag_id)

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        row = await db.scalar(select(EtEnrollment).where(EtEnrollment.user_id == student))
        assert row.join_source == SOURCE_TAG_DEFAULT

    async def test_草稿與已關閉課程不補加入(self, db) -> None:
        """spec：補加入該標籤之所有「**已發布且未關閉**」課程。"""
        teacher = await _user(db, "bf_t04", ROLE_TEACHER)
        student = await _user(db, "bf_s04")
        tag_id = await _tag(db, "護理師_bf04")
        await _course(db, teacher, "草稿課程", tag_id, status=COURSE_DRAFT)
        await _course(db, teacher, "已關閉課程", tag_id, status=COURSE_CLOSED)
        published = await _course(db, teacher, "已發布課程", tag_id)

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        assert await _enrolled_course_ids(db, student) == [published]

    async def test_沒有任何課程可加入時不寄空的彙整信(self, db) -> None:
        student = await _user(db, "bf_s05")
        tag_id = await _tag(db, "護理師_bf05")

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        assert await _mails(db, _DIGEST) == []

    async def test_非學員角色不補加入(self, db) -> None:
        """帶入對象限具學員角色者（FR-ET-US8-02）；教師被貼標不會被塞進課程。"""
        teacher = await _user(db, "bf_t06", ROLE_TEACHER)
        tag_id = await _tag(db, "護理師_bf06")
        await _course(db, teacher, "採血作業", tag_id)
        other_teacher = await _user(db, "bf_t07", ROLE_TEACHER)

        await _service.assign(db, user_id=other_teacher, roles={ROLE_TEACHER}, groups={str(tag_id)}, operator_id=_ADMIN)

        assert await _enrolled_course_ids(db, other_teacher) == []
        assert await _mails(db, _DIGEST) == []

    async def test_已在課程中者不重複加入且不寄信(self, db) -> None:
        teacher = await _user(db, "bf_t08", ROLE_TEACHER)
        student = await _user(db, "bf_s08")
        tag_id = await _tag(db, "護理師_bf08")
        cid = await _course(db, teacher, "採血作業", tag_id)
        now = utcnow()
        db.add(
            EtEnrollment(
                user_id=student,
                course_id=cid,
                join_source="INVITATION_CODE",
                joined_at=now,
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user="SYSTEM",
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        rows = (
            (await db.execute(select(EtEnrollment.enrollment_id).where(EtEnrollment.user_id == student)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert await _mails(db, _DIGEST) == [], "沒有任何新加入的課程就不該寄信"

    async def test_被移除的學員不會被貼標帶回(self, db) -> None:
        """#247 SA Q1 裁示 C 同樣適用於貼標追溯——它也是標籤帶入的一種。"""
        teacher = await _user(db, "bf_t09", ROLE_TEACHER)
        student = await _user(db, "bf_s09")
        tag_id = await _tag(db, "護理師_bf09")
        cid = await _course(db, teacher, "採血作業", tag_id)
        now = utcnow()
        db.add(
            EtEnrollment(
                user_id=student,
                course_id=cid,
                join_source=SOURCE_TAG_DEFAULT,
                joined_at=now,
                completion_status="NOT_STARTED",
                is_removed=True,
                removed_at=now,
                created_user="SYSTEM",
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()

        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups={str(tag_id)}, operator_id=_ADMIN)

        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
        )
        assert row.is_removed is True
        assert await _mails(db, _DIGEST) == []


class TestTagRemovalDoesNothing:
    """AC / FR-ET-US8-06：**移除**標籤對應時既有名單不變動、不寄信。"""

    async def test_移除標籤不動既有選課列也不寄信(self, db) -> None:
        teacher = await _user(db, "bf_t10", ROLE_TEACHER)
        student = await _user(db, "bf_s10")
        tag_id = await _tag(db, "護理師_bf10")
        cid = await _course(db, teacher, "採血作業", tag_id)
        db.add(EtUserTag(user_id=student, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
        now = utcnow()
        db.add(
            EtEnrollment(
                user_id=student,
                course_id=cid,
                join_source=SOURCE_TAG_DEFAULT,
                joined_at=now,
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user="SYSTEM",
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()

        # 目標集合不含該標籤 = 移除對應
        await _service.assign(db, user_id=student, roles={ROLE_STUDENT}, groups=set(), operator_id=_ADMIN)

        assert await _enrolled_course_ids(db, student) == [cid], "已加入者可繼續學習"
        assert await _mails(db, _DIGEST) == []
