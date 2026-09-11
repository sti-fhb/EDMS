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


async def _course(
    db,
    *,
    owner: str,
    name: str,
    status: str = COURSE_PUBLISHED,
    ends_in: timedelta | None = timedelta(days=30),
) -> int:
    """`ends_in` 為 `None` 代表 `OPEN_END_AT` 留空（沒有結束日），負值代表期間已過。"""
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=None if ends_in is None else now + ends_in,
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
    """回應為專案標準的分頁格式（`sti-backend-modules` 慣例）。

    `spec_us7` 的 Acceptance Scenarios 只到 AC 10，此處不掛 AC 編號——掛了會讓後續
    以 spec 編號回溯測試的人去找一條不存在的 AC。
    """

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

    async def test_前端送出的完整參數集合可通過後端驗證(self, client, db) -> None:
        """**契約測試**：這裡的參數集合必須與 `CourseListParams`（前端）逐字一致。

        前後端各有一份查詢參數型別，而兩邊都不驗對方。後端測試若自行多送或少送欄位，
        「前端實際組出的 query string 能不能通過後端 schema」就永遠沒有一層驗過——
        參數改名或加上限時會表現成「篩選送出後 422 或被靜默忽略」，而三層測試各自都綠。

        對應的前端斷言在 `CourseListPage.test.tsx`「送出的查詢參數恰為契約所列」。
        """
        me = await _user(db, "t_cl18")
        tag_id = await _tag(db, "護理師_cl18")
        await db.commit()

        r = await client.get(
            _URL,
            params={"scope": "all", "q": "採血", "tag_id": tag_id, "owner_id": me, "page": 1, "limit": 12},
            headers=_bearer(me),
        )

        assert r.status_code == 200, r.text

    async def test_關鍵字長度上限與前端輸入框一致(self, client, db) -> None:
        """後端 `max_length=100`；前端關鍵字輸入框也必須卡在 100。

        兩邊不一致時使用者打到第 101 個字就 422，而畫面上只會顯示一句「課程清單載入
        失敗」——沒有任何線索指向「你打太長了」。
        """
        me = await _user(db, "t_cl19")
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine", "q": "字" * 101}, headers=_bearer(me))

        assert r.status_code == 422, "後端上限若放寬，前端輸入框的 maxLength 要一起改"


class TestAuthorization:
    """兩支新端點皆掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`。"""

    async def test_學員呼叫課程清單回四零三(self, client, db) -> None:
        me = await _user(db, "s_cl20", roles=(ROLE_STUDENT,))
        await db.commit()

        r = await client.get(_URL, params={"scope": "all"}, headers=_bearer(me))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"

    async def test_學員呼叫篩選標籤回四零三(self, client, db) -> None:
        # 另開一條而非併進上一條：整合測試中預期失敗的請求會回滾前置資料，
        # 同一條裡的第二次呼叫會變成 401（使用者列已不存在）
        me = await _user(db, "s_cl21", roles=(ROLE_STUDENT,))
        await db.commit()

        r = await client.get(f"{_URL}/filter-tags", headers=_bearer(me))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"


class TestFilterTags:
    """`GET /courses/filter-tags`：篩選下拉的來源，語意與 ET02 編輯用的 `/tags` **相反**。"""

    async def test_下拉含已停用標籤(self, client, db) -> None:
        """**這是本端點存在的唯一理由**（`FR-ET-US7-02`）。

        若改用 `/tags`（排除停用者），掛著已停用標籤的歷史課程就從此搜不到，而畫面上
        不會有任何異常——沒有錯誤、沒有空狀態，只是那些課程再也不出現。
        """
        me = await _user(db, "t_cl22")
        retired = await _tag(db, "已裁撤單位_cl22", is_active=False)
        await db.commit()

        r = await client.get(f"{_URL}/filter-tags", headers=_bearer(me))

        assert r.status_code == 200, r.text
        by_id = {t["tag_id"]: t for t in r.json()}
        assert retired in by_id, "停用標籤必須留在篩選下拉裡"
        assert by_id[retired]["is_active"] is False, "前端要據此標示「（已停用）」"

    async def test_與編輯用的_tags_端點確實不同(self, client, db) -> None:
        """兩支端點對同一個停用標籤給出相反的答案——這正是不可互換的證據。"""
        me = await _user(db, "t_cl23")
        retired = await _tag(db, "已裁撤單位_cl23", is_active=False)
        await db.commit()

        filter_tags = await client.get(f"{_URL}/filter-tags", headers=_bearer(me))
        edit_tags = await client.get("/api/et/tags", headers=_bearer(me))

        assert retired in {t["tag_id"] for t in filter_tags.json()}
        assert retired not in {t["tag_id"] for t in edit_tags.json()}


class TestEffectivelyClosed:
    """「`PUBLISHED` 但 `OPEN_END_AT` 已過 = 視同關閉」（#288 SA Q1 裁示 A）。

    到期自動轉 `CLOSED` 屬未實作的 ET-16，故期間已過的課程 `STATUS` 仍是 `PUBLISHED`
    ——清單若只比對 `STATUS`，會把一門學員早已進不去的課列成「已發布」。
    """

    async def test_期間已過者不列入全部課程(self, client, db) -> None:
        owner = await _user(db, "t_cl24")
        viewer = await _user(db, "t_cl25")
        await _course(db, owner=owner, name="期間已過課_cl24", ends_in=-timedelta(days=1))
        await _course(db, owner=owner, name="期間未過課_cl24", ends_in=timedelta(days=1))
        await db.commit()

        r = await client.get(_URL, params={"scope": "all"}, headers=_bearer(viewer))

        names = {c["course_name"] for c in r.json()["data"]}
        assert names == {"期間未過課_cl24"}, "期間已過者視同關閉，不該出現在全部課程"

    async def test_沒有訖止日者仍列入全部課程(self, client, db) -> None:
        """訖止為空＝沒有結束日，不該因為一個缺失的欄位去關掉課程。"""
        owner = await _user(db, "t_cl26")
        viewer = await _user(db, "t_cl27")
        await _course(db, owner=owner, name="無訖止課_cl26", ends_in=None)
        await db.commit()

        r = await client.get(_URL, params={"scope": "all"}, headers=_bearer(viewer))

        assert {c["course_name"] for c in r.json()["data"]} == {"無訖止課_cl26"}

    async def test_我建立的仍看得到期間已過者且標為視同關閉(self, client, db) -> None:
        """教師要管理自己的課，期間已過不代表要從他眼前消失——但要標對狀態。"""
        me = await _user(db, "t_cl28")
        await _course(db, owner=me, name="期間已過課_cl28", ends_in=-timedelta(days=1))
        await _course(db, owner=me, name="期間未過課_cl28", ends_in=timedelta(days=1))
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        by_name = {c["course_name"]: c for c in r.json()["data"]}
        assert by_name["期間已過課_cl28"]["is_closed"] is True
        assert by_name["期間已過課_cl28"]["status"] == COURSE_PUBLISHED, (
            "STATUS 不該被查詢端改寫——視同關閉是應用層的即時判定，不是資料狀態"
        )
        assert by_name["期間未過課_cl28"]["is_closed"] is False

    async def test_手動關閉者亦為視同關閉(self, client, db) -> None:
        me = await _user(db, "t_cl29")
        await _course(db, owner=me, name="手動關閉課_cl29", status=COURSE_CLOSED)
        await db.commit()

        r = await client.get(_URL, params={"scope": "mine"}, headers=_bearer(me))

        card = next(c for c in r.json()["data"] if c["course_name"] == "手動關閉課_cl29")
        assert card["is_closed"] is True
