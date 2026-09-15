"""週報逐學員明細 CSV 下載（T164 / US14 / #325）。

## 授權是本檔的重心（FR-ET-US14-11）

連結出現在信件裡，收件人會直接點——所以「換一個 `course_id` 會怎樣」是必須釘住的。
教師只能下載自己為 `OWNER_ID` 的課程；管理者全域。

## 範圍由呼叫者的角色決定，不由參數決定

不帶 `course_id` 時（週報信中的連結即為此形式）輸出該呼叫者權限範圍內的全部開放中
課程——範本的 `{REPORT_CSV_URL}` 是單一佔位，而一份週報涵蓋多門課，兩者範圍必須一致。
"""

import csv
import io

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    ITEM_MATERIAL,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_CSV = "/api/et/reports/weekly/students.csv"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *roles: str) -> str:
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
    for role in roles:
        db.add(
            EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
        )
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


async def _course(client, db, teacher: str, slug: str) -> dict:
    created = await client.post(
        _COURSES,
        json={
            "course_name": f"明細課程{slug}",
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
    return {"course_id": cid, "item_id": item.json()["item_id"]}


def _rows(body: bytes) -> list[list[str]]:
    """解析回應為列（跳過 BOM）。"""
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


class TestAuthorization:
    async def test_未登入回401(self, client, db) -> None:
        r = await client.get(_CSV)
        assert r.status_code == 401

    async def test_僅具學員角色者回403(self, client, db) -> None:
        """單掛 `get_et_context` 等同「已登入」——學員角色於帳號建立當下即自動授予。"""
        await _user(db, "csv_stu", ROLE_STUDENT)

        r = await client.get(_CSV, headers=_bearer("csv_stu"))

        assert r.status_code == 403

    async def test_教師下載他人課程回403(self, client, db) -> None:
        owner = await _user(db, "csv_own", ROLE_TEACHER)
        other = await _user(db, "csv_other", ROLE_TEACHER)
        ctx = await _course(client, db, owner, "a1")

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(other))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_管理者可下載任一課程(self, client, db) -> None:
        owner = await _user(db, "csv_own2", ROLE_TEACHER)
        admin = await _user(db, "csv_adm", ROLE_ADMIN)
        ctx = await _course(client, db, owner, "a2")

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(admin))

        assert r.status_code == 200, r.text

    async def test_課程不存在回404(self, client, db) -> None:
        await _user(db, "csv_t404", ROLE_TEACHER)

        r = await client.get(_CSV, params={"course_id": 999999}, headers=_bearer("csv_t404"))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_COURSE_001"


class TestScope:
    async def test_教師不帶課程時只含自己的課程(self, client, db) -> None:
        mine = await _user(db, "sc_mine", ROLE_TEACHER)
        theirs = await _user(db, "sc_theirs", ROLE_TEACHER)
        my_course = await _course(client, db, mine, "s1")
        their_course = await _course(client, db, theirs, "s2")
        student = await _user(db, "sc_stu", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=my_course["course_id"])
        await _enroll(db, user_id=student, course_id=their_course["course_id"])

        r = await client.get(_CSV, headers=_bearer(mine))

        assert r.status_code == 200, r.text
        body = r.content.decode("utf-8-sig")
        assert "明細課程s1" in body and "明細課程s2" not in body

    async def test_管理者不帶課程時含全域(self, client, db) -> None:
        teacher = await _user(db, "sc_t2", ROLE_TEACHER)
        admin = await _user(db, "sc_a2", ROLE_ADMIN)
        ctx = await _course(client, db, teacher, "s3")
        student = await _user(db, "sc_stu2", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])

        r = await client.get(_CSV, headers=_bearer(admin))

        assert "明細課程s3" in r.content.decode("utf-8-sig")

    async def test_已關閉課程仍可依課程下載(self, client, db) -> None:
        """FR-ET-US14-11 (4)：連結不另設有效期；教師在課程結束後調歷史明細是正常需求。"""
        teacher = await _user(db, "sc_t3", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "s4")
        student = await _user(db, "sc_stu3", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == ctx["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(teacher))

        assert r.status_code == 200
        assert "明細課程s4" in r.content.decode("utf-8-sig")


class TestContent:
    async def test_欄位與內容(self, client, db) -> None:
        teacher = await _user(db, "ct_t1", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "c1")
        done = await _user(db, "ct_done", ROLE_STUDENT)
        zero = await _user(db, "ct_zero", ROLE_STUDENT)
        for u in (done, zero):
            await _enroll(db, user_id=u, course_id=ctx["course_id"])
        viewed = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(done))
        assert viewed.status_code == 200, viewed.text

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(teacher))

        rows = _rows(r.content)
        assert rows[0] == ["課程名稱", "姓名", "Email", "進度%", "完課狀態", "最後活動時間"]
        by_name = {row[1]: row for row in rows[1:]}
        assert by_name["測試ct_done"][3:5] == ["100", "已完課"]
        assert by_name["測試ct_zero"][3:5] == ["0", "未開始"]
        assert by_name["測試ct_done"][2] == "ct_done@edms.local"

    async def test_已移除學員不出現(self, client, db) -> None:
        teacher = await _user(db, "ct_t2", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "c2")
        gone = await _user(db, "ct_gone", ROLE_STUDENT)
        await _enroll(db, user_id=gone, course_id=ctx["course_id"])
        await db.execute(update(EtEnrollment).where(EtEnrollment.user_id == gone).values(is_removed=True))
        await db.flush()

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(teacher))

        assert "測試ct_gone" not in r.content.decode("utf-8-sig")

    async def test_課程名稱之公式注入被中和(self, client, db) -> None:
        """試算表會把以 `=` 開頭的欄位當公式執行（CWE-1236）。課程名稱是教師自由輸入。"""
        teacher = await _user(db, "ct_t3", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "c3")
        student = await _user(db, "ct_stu3", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(course_name='=HYPERLINK("http://evil")')
        )
        await db.flush()

        r = await client.get(_CSV, params={"course_id": ctx["course_id"]}, headers=_bearer(teacher))

        rows = _rows(r.content)
        assert rows[1][0].startswith("'="), "危險前導字元須被中和為文字"

    async def test_回應為附件且帶BOM(self, client, db) -> None:
        """Excel 以系統 ANSI 開啟無 BOM 的 UTF-8 CSV 會讓中文全部變亂碼，
        而使用者只會看到「檔案壞了」。"""
        teacher = await _user(db, "ct_t4", ROLE_TEACHER)
        await _course(client, db, teacher, "c4")

        r = await client.get(_CSV, headers=_bearer(teacher))

        assert r.content.startswith(b"\xef\xbb\xbf")
        assert "attachment" in r.headers["content-disposition"]
