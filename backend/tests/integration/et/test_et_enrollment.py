"""ET04 我的課程與加入新課程整合測試（US4 / #247）。

規則判定（邀請碼格式、加入資格、清單可見性）已在 `tests/unit/et/test_enrollment_rules.py`
以純函式涵蓋。此處只驗**需要真 DB 才驗得了**的事：

1. `JOIN_SOURCE` 確實寫進 `ET_ENROLLMENT`
2. 被移除的學員撞不到 `UQ_ET_ENROLLMENT_USER_COURSE`——應用層先擋（裁示 C）
3. 重複加入不產生第二列
4. 清單只回自己的課程，且統計與卡片來自同一次查詢
5. 「起始時間未到可加入、但清單不顯示」這組**必須合看才成立**的行為（裁示 A）
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COMPLETION_COMPLETED,
    COMPLETION_NOT_STARTED,
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_MY_COURSES = "/api/et/my-courses"
_PREVIEW = "/api/et/enrollments/preview"
_ENROLLMENTS = "/api/et/enrollments"


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


async def _tag(db, course_id: int, name: str) -> None:
    """把標籤掛到課程上；標籤不存在才建。

    「護理師」「軍人」等是 `data-model` §ET_TAG 的**內建種子**，bootstrap 已經寫進
    DB——無條件 INSERT 會撞 `UQ_ET_TAG_NAME`。
    """
    now = utcnow()
    tag_id = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
    if tag_id is None:
        tag = EtTag(tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=now, deleted=0)
        db.add(tag)
        await db.flush()
        tag_id = tag.tag_id
    db.add(EtCourseTag(course_id=course_id, tag_id=tag_id, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()


async def _course(
    client,
    db,
    teacher: str,
    *,
    code: str,
    status: str = COURSE_PUBLISHED,
    start_offset_days: int = -1,
    name: str = "採血作業新進人員訓練",
) -> int:
    """建課程並直接改成指定狀態 / 邀請碼。

    刻意**不走發布 API**：那需要先備妥章節、教材、標籤、起訖時間與配分才過得了
    檢核（#204 的六項），而本檔要驗的是加入行為，不是發布檢核。走發布 API 會讓
    每條測試都綁著 #204 的規則，那些規則一改，這裡就整片紅。
    """
    created = await client.post(_COURSES, json={"course_name": name}, headers=_bearer(teacher))
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    now = utcnow()
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(
            status=status,
            invitation_code=code,
            open_start_at=now.replace(microsecond=0) + _days(start_offset_days),
            open_end_at=now + _days(365),
        )
    )
    await db.flush()
    return course_id


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


async def _chapter(client, teacher: str, course_id: int, name: str = "第一章") -> int:
    r = await client.post(f"{_COURSES}/{course_id}/chapters", json={"chapter_name": name}, headers=_bearer(teacher))
    assert r.status_code == 201, r.text
    return r.json()["chapter_id"]


async def _join(client, student: str, code: str):
    return await client.post(_ENROLLMENTS, json={"invitation_code": code}, headers=_bearer(student))


async def _preview(client, student: str, code: str):
    return await client.post(_PREVIEW, json={"invitation_code": code}, headers=_bearer(student))


class TestPreview:
    async def test_預覽回課程名稱教師與章節數(self, client, db) -> None:
        """AC 6：驗證通過後顯示課程資訊，學員確認後才加入。"""
        teacher = await _user(db, "t_enr01", ROLE_TEACHER)
        student = await _user(db, "s_enr01")
        cid = await _course(client, db, teacher, code="10000001")
        await _chapter(client, teacher, cid)
        await _chapter(client, teacher, cid, "第二章")

        r = await _preview(client, student, "10000001")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["course_id"] == cid
        assert body["course_name"] == "採血作業新進人員訓練"
        assert body["owner_name"] == "測試t_enr01"
        assert body["chapter_count"] == 2
        assert body["already_joined"] is False

    async def test_預覽不寫入任何資料(self, client, db) -> None:
        """預覽是體驗、不是加入——按「取消」不該留下任何痕跡。"""
        teacher = await _user(db, "t_enr02", ROLE_TEACHER)
        student = await _user(db, "s_enr02")
        cid = await _course(client, db, teacher, code="10000002")

        assert (await _preview(client, student, "10000002")).status_code == 200

        rows = (await db.scalars(select(EtEnrollment).where(EtEnrollment.course_id == cid))).all()
        assert rows == []


class TestJoin:
    async def test_加入寫入邀請碼來源(self, client, db) -> None:
        """AC 7 / ET-MSG-ET04-004。"""
        teacher = await _user(db, "t_enr03", ROLE_TEACHER)
        student = await _user(db, "s_enr03")
        cid = await _course(client, db, teacher, code="10000003")

        r = await _join(client, student, "10000003")

        assert r.status_code == 201, r.text
        assert r.json()["completion_status"] == COMPLETION_NOT_STARTED
        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
        )
        assert row is not None
        assert row.join_source == SOURCE_INVITATION_CODE
        assert row.is_removed is False
        assert row.last_activity_at is None, "加入不是學習動作，不應寫入最後活動時間"

    async def test_查無邀請碼回404(self, client, db) -> None:
        """AC 8 / ET-MSG-ET04-001。"""
        student = await _user(db, "s_enr04")

        r = await _join(client, student, "99999999")

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_ENROLL_001"

    async def test_格式不符與查無共用同一回應(self, client, db) -> None:
        """拆成兩碼會告訴嘗試者「這組格式是對的，只是不存在」。"""
        student = await _user(db, "s_enr05")

        r = await _join(client, student, "abc")

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_ENROLL_001"

    async def test_已關閉課程之邀請碼失效(self, client, db) -> None:
        """AC 9 / ET-MSG-ET04-002：碼沒變，變的是課程狀態。"""
        teacher = await _user(db, "t_enr06", ROLE_TEACHER)
        student = await _user(db, "s_enr06")
        await _course(client, db, teacher, code="10000006", status=COURSE_CLOSED)

        r = await _join(client, student, "10000006")

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_ENROLL_002"

    async def test_重複加入不產生第二列(self, client, db) -> None:
        """AC 10：不重複加入，直接導向該課程——**不是錯誤**。"""
        teacher = await _user(db, "t_enr07", ROLE_TEACHER)
        student = await _user(db, "s_enr07")
        cid = await _course(client, db, teacher, code="10000007")

        assert (await _join(client, student, "10000007")).status_code == 201
        again = await _join(client, student, "10000007")

        assert again.status_code == 201, again.text
        assert again.json()["course_id"] == cid
        rows = (
            await db.scalars(
                select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
            )
        ).all()
        assert len(rows) == 1

        preview = await _preview(client, student, "10000007")
        assert preview.json()["already_joined"] is True


class TestRemovedStudentCannotRejoin:
    """#247 SA Q1 裁示 C。"""

    async def test_被移除之學員重新輸入邀請碼被擋(self, client, db) -> None:
        """必須是 409 `ET_ENROLL_003`，**不是** 500。

        `UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一（刻意，見 `progress/models.py`），
        被移除者那一列還在。少了應用層這道攔截，就會掉進 INSERT 撞唯一鍵，變成
        資料庫錯誤，而衝突對象是一筆學員在前台看不見的列。
        """
        teacher = await _user(db, "t_enr08", ROLE_TEACHER)
        student = await _user(db, "s_enr08")
        cid = await _course(client, db, teacher, code="10000008")
        assert (await _join(client, student, "10000008")).status_code == 201
        await _remove_student(db, student, cid)

        r = await _join(client, student, "10000008")

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_ENROLL_003"

    async def test_被移除之學員預覽亦被擋(self, client, db) -> None:
        """預覽若回 `already_joined=true`，前端會把他導向一門他已無成員資格的課程。"""
        teacher = await _user(db, "t_enr09", ROLE_TEACHER)
        student = await _user(db, "s_enr09")
        cid = await _course(client, db, teacher, code="10000009")
        assert (await _join(client, student, "10000009")).status_code == 201
        await _remove_student(db, student, cid)

        r = await _preview(client, student, "10000009")

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_ENROLL_003"

    async def test_被移除之課程不再出現於清單(self, client, db) -> None:
        """FR-ET-US4-06：前台不再顯示，但學習歷史保留於 DB。"""
        teacher = await _user(db, "t_enr10", ROLE_TEACHER)
        student = await _user(db, "s_enr10")
        cid = await _course(client, db, teacher, code="10000010")
        assert (await _join(client, student, "10000010")).status_code == 201
        await _remove_student(db, student, cid)

        r = await client.get(_MY_COURSES, headers=_bearer(student))

        assert [c["course_id"] for c in r.json()["courses"]] == []
        assert await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
        ) is not None, "學習歷史必須保留"


class TestPendingOpenCourse:
    async def test_起始時間未到可加入但清單不顯示(self, client, db) -> None:
        """#247 SA Q2 裁示 A + AC 4——**兩件事必須合看**。

        分開看都正常：加入成功是對的，清單不顯示也是對的（AC 4）。湊在一起才是那個
        死角——學員看到「已加入」✓ 卻在清單一片空白，以為失敗而反覆重試。
        `pending_open` 就是讓前端把提示換成「課程開放後將出現於清單」的依據。
        """
        teacher = await _user(db, "t_enr11", ROLE_TEACHER)
        student = await _user(db, "s_enr11")
        await _course(client, db, teacher, code="10000011", start_offset_days=7)

        joined = await _join(client, student, "10000011")
        listed = await client.get(_MY_COURSES, headers=_bearer(student))

        assert joined.status_code == 201, joined.text
        assert joined.json()["pending_open"] is True
        assert listed.json()["courses"] == []
        assert listed.json()["summary"]["joined"] == 0

    async def test_預覽帶開放時間供前端提示(self, client, db) -> None:
        teacher = await _user(db, "t_enr12", ROLE_TEACHER)
        student = await _user(db, "s_enr12")
        await _course(client, db, teacher, code="10000012", start_offset_days=7)

        r = await _preview(client, student, "10000012")

        assert r.status_code == 200
        assert r.json()["open_start_at"] is not None


class TestMyCourses:
    async def test_統計與卡片來自同一份資料(self, client, db) -> None:
        """AC 2 / AC 3。"""
        teacher = await _user(db, "t_enr13", ROLE_TEACHER)
        student = await _user(db, "s_enr13")
        cid = await _course(client, db, teacher, code="10000013")
        await _chapter(client, teacher, cid)
        await _tag(db, cid, "護理師")
        await _tag(db, cid, "軍人")
        assert (await _join(client, student, "10000013")).status_code == 201

        body = (await client.get(_MY_COURSES, headers=_bearer(student))).json()

        assert body["summary"] == {"joined": 1, "in_progress": 0, "not_started": 1, "completed": 0}
        card = body["courses"][0]
        assert card["course_name"] == "採血作業新進人員訓練"
        assert card["tags"] == ["護理師", "軍人"]
        assert card["chapter_count"] == 1
        assert card["open_start_at"] is not None and card["open_end_at"] is not None
        assert card["progress_pct"] == 0, "進度依賴 ET_PROGRESS（ET-5），本 issue 恆為 0"

    async def test_已完成課程計入完成數(self, client, db) -> None:
        teacher = await _user(db, "t_enr14", ROLE_TEACHER)
        student = await _user(db, "s_enr14")
        cid = await _course(client, db, teacher, code="10000014")
        assert (await _join(client, student, "10000014")).status_code == 201
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
            .values(completion_status=COMPLETION_COMPLETED)
        )
        await db.flush()

        summary = (await client.get(_MY_COURSES, headers=_bearer(student))).json()["summary"]

        assert summary == {"joined": 1, "in_progress": 0, "not_started": 0, "completed": 1}

    async def test_已關閉課程仍顯示(self, client, db) -> None:
        """AC 5 / AC 13：顯示「已關閉」標示、可唯讀回看。

        這是 `ET-4` 與 `publish_rules.is_visible_to_student` 的分歧點——後者對
        `CLOSED` 回 False。若清單直接沿用該函式，已關閉課程會整個從學員眼前消失。
        """
        teacher = await _user(db, "t_enr15", ROLE_TEACHER)
        student = await _user(db, "s_enr15")
        cid = await _course(client, db, teacher, code="10000015")
        assert (await _join(client, student, "10000015")).status_code == 201
        await db.execute(update(EtCourse).where(EtCourse.course_id == cid).values(status=COURSE_CLOSED))
        await db.flush()

        body = (await client.get(_MY_COURSES, headers=_bearer(student))).json()

        assert [c["course_id"] for c in body["courses"]] == [cid]
        assert body["courses"][0]["status"] == COURSE_CLOSED

    async def test_只回自己的課程(self, client, db) -> None:
        teacher = await _user(db, "t_enr16", ROLE_TEACHER)
        mine = await _user(db, "s_enr16a")
        other = await _user(db, "s_enr16b")
        cid = await _course(client, db, teacher, code="10000016")
        assert (await _join(client, other, "10000016")).status_code == 201

        body = (await client.get(_MY_COURSES, headers=_bearer(mine))).json()

        assert body["courses"] == []
        assert body["summary"]["joined"] == 0
        assert cid  # 課程存在，只是不屬於 mine

    async def test_無退出課程之端點(self, client, db) -> None:
        """AC 11 / FR-ET-US4-06：學員無主動退出能力。

        以「端點不存在」表達而非「端點存在但擋住」——後者會讓下一個人以為它只是
        暫時關著。
        """
        teacher = await _user(db, "t_enr17", ROLE_TEACHER)
        student = await _user(db, "s_enr17")
        cid = await _course(client, db, teacher, code="10000017")
        assert (await _join(client, student, "10000017")).status_code == 201

        r = await client.delete(f"{_ENROLLMENTS}/{cid}", headers=_bearer(student))

        assert r.status_code in (404, 405)


async def _remove_student(db, user_id: str, course_id: int) -> None:
    """教師移除學員（US9 的動作，此處直接寫 DB）——標記而非刪列。"""
    await db.execute(
        update(EtEnrollment)
        .where(EtEnrollment.user_id == user_id, EtEnrollment.course_id == course_id)
        .values(is_removed=True, removed_at=utcnow())
    )
    await db.flush()
