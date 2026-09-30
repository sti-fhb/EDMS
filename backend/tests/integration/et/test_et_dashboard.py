"""首頁教育訓練儀表板整合測試（#453 / #89 的 P3）。

此處只驗**需要真 DB 才驗得了**的事：跨表聚合、依角色分流、以及三個「只有真資料才會
暴露」的陷阱——死欄位、`IS_ALL` 標籤、一人多標籤的計數灌大。

純推導（`percent` 的空母體、`days_left` 的捨去）於 `tests/unit/et/test_stats_rules.py`。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.params.models import DpParamDetail
from app.dp.users.models import DpUser
from app.et.catalog.models import EtTag, EtUserTag
from app.et.constants import (
    COMPLETION_NOT_STARTED,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_DASHBOARD = "/api/et/dashboard"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, roles: tuple[str, ...]) -> str:
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


async def _course(
    db,
    *,
    owner: str,
    name: str,
    status: str = COURSE_PUBLISHED,
    ends_in_days: int | None = 30,
) -> int:
    """建課程。`ends_in_days` 為 `None` 時訖止留空（用於「無期限不算逾期」）。"""
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=None if ends_in_days is None else now + timedelta(days=ends_in_days),
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


async def _one_item_course(db, *, owner: str, name: str, **kwargs) -> tuple[int, int]:
    """建一門**只有一個項目**的課程，回 `(course_id, item_id)`。

    只有一個項目是刻意的：完課判定是 `done >= total`，項目數為 1 時「完課」只要一筆
    `ET_PROGRESS`，測試造資料最省且邊界最清楚。
    """
    course_id = await _course(db, owner=owner, name=name, **kwargs)
    now = utcnow()
    ch = EtChapter(
        course_id=course_id,
        chapter_name="第一章",
        sort_order=1,
        version=0,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(ch)
    await db.flush()
    material = EtMaterial(material_name="教材", version=0, created_user=owner, created_date=now, deleted=0)
    db.add(material)
    await db.flush()
    item = EtItem(
        chapter_id=ch.chapter_id,
        item_type=ITEM_MATERIAL,
        sort_order=1,
        material_id=material.material_id,
        quiz_id=None,
        version=0,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(item)
    await db.flush()
    return course_id, item.item_id


async def _enroll(db, user_id: str, course_id: int) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            # ⚠️ 一律建成 NOT_STARTED——這就是正式環境的樣子（該欄位寫入後永不更新）。
            completion_status=COMPLETION_NOT_STARTED,
            is_removed=False,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _complete(db, user_id: str, course_id: int, item_id: int) -> None:
    db.add(
        EtProgress(
            user_id=user_id,
            course_id=course_id,
            item_id=item_id,
            is_completed=True,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


async def _tag(db, name: str, *, is_all: bool = False) -> int:
    now = utcnow()
    tag = EtTag(
        tag_name=name,
        is_active=True,
        is_all=is_all,
        is_builtin=False,
        display_order=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _assign_tag(db, user_id: str, tag_id: int) -> None:
    db.add(EtUserTag(user_id=user_id, tag_id=tag_id, created_user="admin01", created_date=utcnow(), deleted=0))
    await db.flush()


class TestRoleRouting:
    """哪張卡回 `None`、哪張回內容，由角色決定（前端才依「有無資料」決定渲染）。"""

    async def test_純學員只拿到學員卡(self, client, db) -> None:
        student = await _user(db, "d_stu01", roles=(ROLE_STUDENT,))

        body = (await client.get(_DASHBOARD, headers=_bearer(student))).json()

        assert body["student"] is not None
        assert body["teacher"] is None, "沒有教師角色就不該拿到教師卡"
        assert body["admin"] is None

    async def test_純教師拿不到學員卡(self, client, db) -> None:
        teacher = await _user(db, "d_tea01", roles=(ROLE_TEACHER,))

        body = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()

        assert body["student"] is None
        assert body["teacher"] is not None
        assert body["admin"] is None

    async def test_多重身分三張卡同時拿到(self, client, db) -> None:
        both = await _user(db, "d_all01", roles=(ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN))

        body = (await client.get(_DASHBOARD, headers=_bearer(both))).json()

        assert body["student"] is not None
        assert body["teacher"] is not None
        assert body["admin"] is not None

    async def test_有角色但沒資料回空內容而非_None(self, client, db) -> None:
        """⚠️ 空內容與 `None` 是不同的兩件事（見 `EtDashboard` 的 docstring）。

        #89 的空卡規則由**前端**依有無資料執行；後端若把「沒資料」也回成 `None`，
        日後想對「他是教師但目前沒有待辦」加一句正向訊息時就分不出來了。
        """
        teacher = await _user(db, "d_tea02", roles=(ROLE_TEACHER,))

        body = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()

        assert body["teacher"] == {"ending_soon": [], "draft_count": 0}


class TestStudentCard:
    async def test_數字與_my_courses_同源(self, client, db) -> None:
        """同源以「呼叫同一支」保證，故兩個端點的數字必須逐欄相等。"""
        teacher = await _user(db, "d_tea03", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu02", roles=(ROLE_STUDENT,))
        course_id, item_id = await _one_item_course(db, owner=teacher, name="已完課的課")
        another, _ = await _one_item_course(db, owner=teacher, name="還沒開始的課")
        await _enroll(db, student, course_id)
        await _enroll(db, student, another)
        await _complete(db, student, course_id, item_id)

        card = (await client.get(_DASHBOARD, headers=_bearer(student))).json()["student"]
        summary = (await client.get("/api/et/my-courses", headers=_bearer(student))).json()["summary"]

        assert card == {k: summary[k] for k in card}, f"與 my-courses 分歧：{card} vs {summary}"
        assert card["joined"] == 2
        assert card["completed"] == 1


class TestTeacherCard:
    async def test_只含自己的課(self, client, db) -> None:
        mine = await _user(db, "d_tea04", roles=(ROLE_TEACHER,))
        other = await _user(db, "d_tea05", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu03", roles=(ROLE_STUDENT,))
        my_course, _ = await _one_item_course(db, owner=mine, name="我的課", ends_in_days=1)
        their_course, _ = await _one_item_course(db, owner=other, name="別人的課", ends_in_days=1)
        await _enroll(db, student, my_course)
        await _enroll(db, student, their_course)

        card = (await client.get(_DASHBOARD, headers=_bearer(mine))).json()["teacher"]

        names = [line["course_name"] for line in card["ending_soon"]]
        assert names == ["我的課"], "別人的課不得出現——他對那門課什麼都做不了"

    async def test_全班都完課的課不列(self, client, db) -> None:
        teacher = await _user(db, "d_tea06", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu04", roles=(ROLE_STUDENT,))
        course_id, item_id = await _one_item_course(db, owner=teacher, name="大家都完課了", ends_in_days=1)
        await _enroll(db, student, course_id)
        await _complete(db, student, course_id, item_id)

        card = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()["teacher"]

        assert card["ending_soon"] == [], "不需要教師做任何事的課留著只會稀釋真正要處理的那幾門"

    async def test_未到門檻的課不列且門檻取自_DP_PARAM(self, client, db) -> None:
        """⚠️ 門檻必須與加急提醒信同源，否則會出現「首頁說要注意了、信還沒寄」。"""
        teacher = await _user(db, "d_tea07", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu05", roles=(ROLE_STUDENT,))
        course_id, _ = await _one_item_course(db, owner=teacher, name="還有 10 天", ends_in_days=10)
        await _enroll(db, student, course_id)

        before = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()["teacher"]
        assert before["ending_soon"] == [], "預設門檻 3 天，10 天後到期的課不該出現"

        # ⚠️ 該參數已由 migration seed（預設 3），故是 UPDATE 不是 INSERT——
        # INSERT 會撞 `DP_PARAM_D` 的唯一鍵，而那個錯誤看起來會像「測試寫錯」。
        await db.execute(
            update(DpParamDetail)
            .where(DpParamDetail.param_id == "ET_URGENT_REMIND_DAYS", DpParamDetail.param_key == "VALUE")
            .values(param_value="14")
        )
        await db.flush()

        after = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()["teacher"]
        assert [line["course_name"] for line in after["ending_soon"]] == ["還有 10 天"]

    async def test_草稿數只算自己未發布的(self, client, db) -> None:
        teacher = await _user(db, "d_tea08", roles=(ROLE_TEACHER,))
        other = await _user(db, "d_tea09", roles=(ROLE_TEACHER,))
        await _course(db, owner=teacher, name="我的草稿", status=COURSE_DRAFT)
        await _course(db, owner=teacher, name="我已發布的", status=COURSE_PUBLISHED)
        await _course(db, owner=other, name="別人的草稿", status=COURSE_DRAFT)

        card = (await client.get(_DASHBOARD, headers=_bearer(teacher))).json()["teacher"]

        assert card["draft_count"] == 1


class TestAdminCardTraps:
    """管理者卡的三個陷阱——都會產生「看起來合理但錯」的數字。"""

    async def test_完成率不讀死欄位(self, client, db) -> None:
        """🔴 `ET_ENROLLMENT.COMPLETION_STATUS` 建立後**永不更新**（全專案無 update）。

        本測試的選課列一律是 `NOT_STARTED`——那就是正式環境的樣子。若實作改讀該欄，
        完成率會變成 0%，而畫面上完全看不出異常。
        """
        admin = await _user(db, "d_adm01", roles=(ROLE_ADMIN,))
        teacher = await _user(db, "d_tea10", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu06", roles=(ROLE_STUDENT,))
        course_id, item_id = await _one_item_course(db, owner=teacher, name="完成率測試")
        await _enroll(db, student, course_id)
        await _complete(db, student, course_id, item_id)

        stored = (
            await db.scalars(select(EtEnrollment.completion_status).where(EtEnrollment.course_id == course_id))
        ).all()
        assert list(stored) == [COMPLETION_NOT_STARTED], "前置條件：該欄仍是建立時的值"

        card = (await client.get(_DASHBOARD, headers=_bearer(admin))).json()["admin"]

        assert Decimal(card["completion_rate"]) == Decimal("100.00")

    async def test_全體標籤不出現在各單位(self, client, db) -> None:
        """⚠️ `IS_ALL` 不逐人建 `ET_USER_TAG` 列，直接 join 會顯示 0 人。

        而且它的達成率等同全站完成率，與卡片上方那個數字重複。
        """
        admin = await _user(db, "d_adm02", roles=(ROLE_ADMIN,))
        teacher = await _user(db, "d_tea11", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu07", roles=(ROLE_STUDENT,))
        course_id, _ = await _one_item_course(db, owner=teacher, name="標籤測試")
        await _enroll(db, student, course_id)
        all_tag = await _tag(db, "ZT全體", is_all=True)
        unit_tag = await _tag(db, "ZT護理師")
        # 即使有人被手動掛上「全體」，它仍不該出現
        await _assign_tag(db, student, all_tag)
        await _assign_tag(db, student, unit_tag)

        card = (await client.get(_DASHBOARD, headers=_bearer(admin))).json()["admin"]

        names = [u["tag_name"] for u in card["by_unit"]]
        assert "ZT全體" not in names
        assert "ZT護理師" in names

    async def test_一人多標籤不灌大整體人次(self, client, db) -> None:
        """⚠️ 依單位分組是本查詢唯一的一對多。整體那支若也 join 標籤就是笛卡兒積。

        一位學員掛三個標籤：`by_unit` 三列各 1 人（正確，各單位各自看自己的人），
        但 `completion_rate` 的母體仍只有 1 人次。
        """
        admin = await _user(db, "d_adm03", roles=(ROLE_ADMIN,))
        teacher = await _user(db, "d_tea12", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu08", roles=(ROLE_STUDENT,))
        course_id, item_id = await _one_item_course(db, owner=teacher, name="多標籤測試")
        await _enroll(db, student, course_id)
        await _complete(db, student, course_id, item_id)
        for name in ("ZT甲單位", "ZT乙單位", "ZT丙單位"):
            await _assign_tag(db, student, await _tag(db, name))

        card = (await client.get(_DASHBOARD, headers=_bearer(admin))).json()["admin"]

        assert len([u for u in card["by_unit"] if u["tag_name"].startswith("ZT")]) == 3
        assert Decimal(card["completion_rate"]) == Decimal("100.00"), "整體不得因為標籤數而被灌大或稀釋"

    async def test_無訖止的課不算逾期(self, client, db) -> None:
        """沒有期限就無從逾期；計入會把「永遠開放的課」全數打成逾期。"""
        admin = await _user(db, "d_adm04", roles=(ROLE_ADMIN,))
        teacher = await _user(db, "d_tea13", roles=(ROLE_TEACHER,))
        student = await _user(db, "d_stu09", roles=(ROLE_STUDENT,))
        course_id, _ = await _one_item_course(db, owner=teacher, name="沒有訖止", ends_in_days=None)
        await _enroll(db, student, course_id)

        card = (await client.get(_DASHBOARD, headers=_bearer(admin))).json()["admin"]

        assert card["overdue_incomplete"] == 0

    async def test_各單位依達成率由低到高(self, client, db) -> None:
        """管理者要找的是落後的那一個，最好的排最前面等於要他從尾巴讀起。"""
        admin = await _user(db, "d_adm05", roles=(ROLE_ADMIN,))
        teacher = await _user(db, "d_tea14", roles=(ROLE_TEACHER,))
        done = await _user(db, "d_stu10", roles=(ROLE_STUDENT,))
        undone = await _user(db, "d_stu11", roles=(ROLE_STUDENT,))
        course_id, item_id = await _one_item_course(db, owner=teacher, name="排序測試")
        await _enroll(db, done, course_id)
        await _enroll(db, undone, course_id)
        await _complete(db, done, course_id, item_id)
        await _assign_tag(db, done, await _tag(db, "ZT高分單位"))
        await _assign_tag(db, undone, await _tag(db, "ZT低分單位"))

        card = (await client.get(_DASHBOARD, headers=_bearer(admin))).json()["admin"]

        ordered = [u["tag_name"] for u in card["by_unit"] if u["tag_name"].startswith("ZT")]
        assert ordered == ["ZT低分單位", "ZT高分單位"]
