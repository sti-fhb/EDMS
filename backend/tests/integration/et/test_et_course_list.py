"""ET01 課程列表查詢整合測試（US7 / #299）。

此處只驗**需要真 DB 才驗得了**的事：

1. 兩種 `scope` 的狀態過濾（「我建立的」含草稿與已關閉；「全部課程」只有已發布）
2. 三種篩選（關鍵字含萬用字元跳脫、標籤、建立者）
3. 卡片的兩個聚合值（章節數、**在籍**學員數）
"""

from datetime import timedelta

import pytest

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtChapter, EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_URL = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, roles: tuple[str, ...] = (ROLE_TEACHER,), name: str | None = None) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=name or f"測試{user_id}",
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


async def _course(db, *, owner: str, name: str, status: str = COURSE_PUBLISHED) -> int:
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=now + timedelta(days=30),
        version=0,
        require_approval=False,
        urgent_remind_sent=False,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    return course.course_id


async def _tag(db, name: str, *, is_active: bool = True) -> int:
    now = utcnow()
    tag = EtTag(tag_name=name, is_active=is_active, created_user="admin01", created_date=now, deleted=0)
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _attach_tag(db, course_id: int, tag_id: int) -> None:
    now = utcnow()
    db.add(EtCourseTag(course_id=course_id, tag_id=tag_id, created_user="admin01", created_date=now, deleted=0))
    await db.flush()


async def _chapter(db, course_id: int, name: str, order: int) -> None:
    now = utcnow()
    db.add(
        EtChapter(
            course_id=course_id,
            chapter_name=name,
            sort_order=order,
            version=0,
            created_user="admin01",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _enroll(db, user_id: str, course_id: int, *, removed: bool = False) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status="NOT_STARTED",
            is_removed=removed,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


class TestScopeFiltering:
    """AC 1 / AC 2：兩種分頁的狀態過濾相反。"""

    async def test_我建立的含草稿與已關閉(self, client, db) -> None:
        """教師要管理自己的課程，草稿與已關閉都得看得到。"""
        me = await _user(db, "t_cl01")
        await _course(db, owner=me, name="草稿課", status="DRAFT")
        await _course(db, owner=me, name="已發布課", status=COURSE_PUBLISHED)
        await _course(db, owner=me, name="已關閉課", status=COURSE_CLOSED)
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        assert r.status_code == 200, r.text
        names = {c["course_name"] for c in r.json()["data"]}
        assert names == {"草稿課", "已發布課", "已關閉課"}

    async def test_全部課程排除草稿與已關閉(self, client, db) -> None:
        """**草稿的存在對他人是秘密**；已關閉者不列入（`FR-ET-US7-01`）。"""
        owner = await _user(db, "t_cl02")
        viewer = await _user(db, "t_cl03")
        await _course(db, owner=owner, name="他人草稿", status="DRAFT")
        await _course(db, owner=owner, name="他人已發布", status=COURSE_PUBLISHED)
        await _course(db, owner=owner, name="他人已關閉", status=COURSE_CLOSED)
        await db.commit()

        r = await client.get(_URL, params={"scope": "all"}, headers=_bearer(viewer))

        assert r.status_code == 200, r.text
        names = {c["course_name"] for c in r.json()["data"]}
        assert names == {"他人已發布"}, "草稿與已關閉都不該出現在全部課程"

    async def test_我建立的不含他人課程(self, client, db) -> None:
        me = await _user(db, "t_cl04")
        other = await _user(db, "t_cl05")
        await _course(db, owner=me, name="我的")
        await _course(db, owner=other, name="他的")
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        assert {c["course_name"] for c in r.json()["data"]} == {"我的"}

    async def test_is_owner_正確標示(self, client, db) -> None:
        """前端據此決定「檢視」標籤與進入模式（AC 7 / 8）。"""
        me = await _user(db, "t_cl06")
        other = await _user(db, "t_cl07")
        await _course(db, owner=me, name="我的課")
        await _course(db, owner=other, name="他的課")
        await db.commit()

        r = await client.get(_URL, params={"scope": "all"}, headers=_bearer(me))

        by_name = {c["course_name"]: c for c in r.json()["data"]}
        assert by_name["我的課"]["is_owner"] is True
        assert by_name["他的課"]["is_owner"] is False


class TestFilters:
    """AC 3 / 4 / 5。"""

    async def test_關鍵字比對課程名稱(self, client, db) -> None:
        me = await _user(db, "t_cl08")
        await _course(db, owner=me, name="採血作業新進人員訓練")
        await _course(db, owner=me, name="捐血人健康評估")
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine", "q": "採血"}, headers=_bearer(me))

        assert {c["course_name"] for c in r.json()["data"]} == {"採血作業新進人員訓練"}

    async def test_關鍵字的萬用字元被跳脫(self, client, db) -> None:
        """**不跳脫的話 `%` 會變成「列出全部」**，而且不會有任何錯誤訊息。"""
        me = await _user(db, "t_cl09")
        await _course(db, owner=me, name="採血作業")
        await _course(db, owner=me, name="捐血評估")
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine", "q": "%"}, headers=_bearer(me))

        assert r.json()["data"] == [], "`%` 應被當成字面值比對，而非萬用字元"

    async def test_多標籤課程任一命中即列出(self, client, db) -> None:
        """一課程多標籤，選其中任一都要找得到（`FR-ET-US7-02`）。"""
        me = await _user(db, "t_cl10")
        nurse = await _tag(db, "護理師_cl10")
        soldier = await _tag(db, "軍人_cl10")
        both = await _course(db, owner=me, name="雙標籤課")
        await _attach_tag(db, both, nurse)
        await _attach_tag(db, both, soldier)
        await _course(db, owner=me, name="無標籤課")
        await db.commit()

        for tag_id in (nurse, soldier):
            r = await client.get(_URL, params={"scope": "mine", "tag_id": tag_id}, headers=_bearer(me))
            assert {c["course_name"] for c in r.json()["data"]} == {"雙標籤課"}, f"tag {tag_id} 沒命中"

    async def test_停用標籤仍可用於篩選(self, client, db) -> None:
        """**要查得到掛著已停用標籤的歷史課程**——否則舊課程從此搜不到。"""
        me = await _user(db, "t_cl11")
        retired = await _tag(db, "已停用單位_cl11", is_active=False)
        course_id = await _course(db, owner=me, name="舊課程")
        await _attach_tag(db, course_id, retired)
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine", "tag_id": retired}, headers=_bearer(me))

        assert {c["course_name"] for c in r.json()["data"]} == {"舊課程"}

    async def test_全部課程可依建立者篩選(self, client, db) -> None:
        a = await _user(db, "t_cl12")
        b = await _user(db, "t_cl13")
        await _course(db, owner=a, name="A 的課")
        await _course(db, owner=b, name="B 的課")
        await db.commit()

        r = await client.get(_URL, params={"scope": "all", "owner_id": a}, headers=_bearer(b))

        assert {c["course_name"] for c in r.json()["data"]} == {"A 的課"}


class TestCardFields:
    """AC 6：卡片欄位齊全，且兩個聚合值正確。"""

    async def test_清單回傳章節數與在籍學員數(self, client, db) -> None:
        """⚠️ **學員數要排除已移除者**——`IS_REMOVED` 與 `DELETED` 語意不同，兩者都要濾。

        卡片上的「28 位學員」問的是「現在有幾個人在上」，不是「歷來有幾個人加入過」。
        """
        me = await _user(db, "t_cl14", name="王老師")
        course_id = await _course(db, owner=me, name="有內容的課")
        await _chapter(db, course_id, "第一章", 1)
        await _chapter(db, course_id, "第二章", 2)
        s1 = await _user(db, "s_cl14a", roles=(ROLE_STUDENT,))
        s2 = await _user(db, "s_cl14b", roles=(ROLE_STUDENT,))
        s3 = await _user(db, "s_cl14c", roles=(ROLE_STUDENT,))
        await _enroll(db, s1, course_id)
        await _enroll(db, s2, course_id)
        await _enroll(db, s3, course_id, removed=True)
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        card = next(c for c in r.json()["data"] if c["course_name"] == "有內容的課")
        assert card["chapter_count"] == 2
        assert card["student_count"] == 2, "已移除的學員不計入"
        assert card["owner_name"] == "王老師"
        assert card["open_start_at"] is not None
        assert card["open_end_at"] is not None

    async def test_卡片帶出標籤清單(self, client, db) -> None:
        me = await _user(db, "t_cl15")
        tag_id = await _tag(db, "護理師_cl15")
        course_id = await _course(db, owner=me, name="有標籤的課")
        await _attach_tag(db, course_id, tag_id)
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        card = next(c for c in r.json()["data"] if c["course_name"] == "有標籤的課")
        assert [t["tag_name"] for t in card["tags"]] == ["護理師_cl15"]


class TestPaginationShape:
    """AC 11：回應為專案標準的 `{ data, meta }`。"""

    async def test_回應為_data_meta_標準格式(self, client, db) -> None:
        me = await _user(db, "t_cl16")
        await _course(db, owner=me, name="任一課程")
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 10}, headers=_bearer(me))

        body = r.json()
        assert isinstance(body["data"], list)
        assert {"total", "page", "limit", "total_pages"} <= set(body["meta"])

    async def test_scope_非法值回四二二(self, client, db) -> None:
        """由 pydantic `Literal` 擋下，不必自寫驗證。"""
        me = await _user(db, "t_cl17")
        await db.commit()

        r = await client.get(_URL, params={"scope": "everything"}, headers=_bearer(me))

        assert r.status_code == 422, r.text
