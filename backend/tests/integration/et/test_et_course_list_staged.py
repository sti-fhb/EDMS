"""ET01 課程卡片讀暫存版（US7 / #813）。

## 本檔要守的事

已關閉課程按「保留編輯」存下的編輯，**詳細頁的擁有者看得到、ET01 卡片看不到**——同一個
人、同一門課、兩個畫面兩種答案（2026-10-22 手測回報）。

`course/service.py` 的 `get` 早就定下規則：**只有擁有者看得到暫存版本**，他人閱覽與學員端
一律看已生效版本。本案把那條既有決定延伸到清單，⛔ **不是新的設計分歧**。

## 為何另開一個檔

`test_et_course_list.py` 已 849 行，而本案要加的測試自帶一組「建暫存列」的 helper
（既有檔的 helper 全是活表的）。比照 #682 的拆檔教訓，新主題進新檔。

## 🔴 N+1 的斷言方式

AC 明寫「**以查詢次數斷言，⛔ 不可只驗結果正確**」。專案原本沒有查詢計數工具
（`before_cursor_execute` / `query_count` 全庫零命中），本檔自建 `count_sql`。

⚠️ 斷言的是「**次數不隨筆數成長**」，⛔ **不是「等於某個數字」**：絕對值會在任何人加一次
無關查詢時變紅，於是下一個人把數字改大——守門就退化成「記錄現況」，再也擋不住 N+1。
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ROLE_TEACHER,
)
from app.et.course.models import EtChapter, EtCourse, EtCourseContentStage
from app.et.course.stage_rules import ENTITY_CHAPTER, ENTITY_COURSE, ENTITY_COURSE_TAG
from app.et.roles.models import EtUserRole
from tests.integration.et._tag_pairs import all_units_id

pytestmark = pytest.mark.integration

_URL = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, name: str | None = None) -> str:
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
    db.add(
        EtUserRole(user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
    )
    await db.flush()
    return user_id


async def _course(
    db,
    owner_id: str,
    name: str,
    *,
    status: str = COURSE_CLOSED,
    days_from_now: int = -5,
) -> int:
    """建一門課。預設為**已關閉**（訖止在過去）——本案的主要情境。"""
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        owner_id=owner_id,
        open_start_at=now - timedelta(days=30),
        open_end_at=now + timedelta(days=days_from_now),
        version=0,
        require_approval=False,
        urgent_remind_sent=False,
        created_user=owner_id,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    return course.course_id


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


async def _tag(db, name: str) -> int:
    now = utcnow()
    tag = EtTag(tag_name=name, is_active=True, created_user="admin01", created_date=now, deleted=0)
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _attach_tag(db, course_id: int, tag_id: int, unit_tag_id: int) -> None:
    now = utcnow()
    db.add(
        EtCourseTag(
            unit_tag_id=unit_tag_id,
            course_id=course_id,
            tag_id=tag_id,
            created_user="admin01",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _stage_node(
    db,
    course_id: int,
    entity_type: str,
    payload: dict,
    *,
    source_id: int | None = None,
    parent_stage_id: int | None = None,
    sort_order: int = 0,
    deleted: int = 0,
) -> int:
    """直接寫一列暫存資料。

    ⚠️ **刻意用 DB 直寫而非走 API**：走編輯 API 建暫存會把「編輯端點是否正確」一起綁進
    本檔的測試，而本案要驗的是**清單怎麼讀**。直寫讓前置條件精準且不受編輯端變動影響。
    """
    now = utcnow()
    node = EtCourseContentStage(
        course_id=course_id,
        entity_type=entity_type,
        source_id=source_id,
        parent_stage_id=parent_stage_id,
        sort_order=sort_order,
        payload=json.dumps(payload, default=str),
        version=0,
        deleted=deleted,
        created_user="admin01",
        created_date=now,
    )
    db.add(node)
    await db.flush()
    return node.stage_id


async def _staged_course(
    db,
    course_id: int,
    *,
    course_name: str,
    chapters: int = 0,
    deleted_chapters: int = 0,
    tag_pairs: list[tuple[int, int]] | None = None,
    open_end_days: int = 400,
) -> int:
    """為課程建一棵最小暫存樹：課程節點 + N 個章節 + 配對。"""
    now = utcnow()
    course_stage_id = await _stage_node(
        db,
        course_id,
        ENTITY_COURSE,
        {
            "course_name": course_name,
            "description": None,
            "open_start_at": now - timedelta(days=1),
            "open_end_at": now + timedelta(days=open_end_days),
            "require_approval": False,
        },
        source_id=course_id,
    )
    for i in range(chapters):
        await _stage_node(db, course_id, ENTITY_CHAPTER, {"chapter_name": f"暫存章節{i}"}, sort_order=i)
    # 軟刪的章節：教師在暫存裡刪掉的，⛔ 不該計入卡片數字
    for i in range(deleted_chapters):
        await _stage_node(
            db, course_id, ENTITY_CHAPTER, {"chapter_name": f"刪掉的{i}"}, sort_order=100 + i, deleted=1
        )
    for unit_id, tag_id in tag_pairs or []:
        await _stage_node(
            db,
            course_id,
            ENTITY_COURSE_TAG,
            {"unit_tag_id": unit_id, "tag_id": tag_id},
            parent_stage_id=course_stage_id,
        )
    return course_stage_id


@pytest.fixture
def count_sql(db):
    """計數本測試期間實際送出的 SQL 敘述。

    🔴 **先於實作建立**（#813 實作順序第 1 步）：要先量到「現況是固定成本」，改完才有對照
    組。先改再補計數，量到的是改後的數字，「有沒有變成 N+1」就沒有基準可比。

    ⚠️ 掛在 `db` 綁定的 **sync connection** 上——`db` 是 `AsyncSession(bind=conn)`
    （見 `tests/integration/conftest.py`），事件要掛在底層的 sync 物件。
    """
    stmts: list[str] = []
    bind = db.get_bind()
    target = getattr(bind, "sync_connection", None) or getattr(bind, "sync_engine", None) or bind

    def _on_exec(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        stmts.append(statement)

    event.listen(target, "before_cursor_execute", _on_exec)
    yield stmts
    event.remove(target, "before_cursor_execute", _on_exec)


class TestQueryCountBaseline:
    """🔴 第 1 步：先證明**現況**的清單查詢是固定成本。

    這組在實作之前就必須全綠——它是之後判斷「有沒有退化成 N+1」的基準線。
    """

    async def test_計數器真的數得到(self, client, db, count_sql):
        """⚠️ 先驗工具本身。

        一個永遠回空陣列的計數器會讓之後所有 N+1 斷言恆真——那比沒有測試更糟，因為它
        看起來是綠的。
        """
        owner = await _user(db, "QC1")
        await _course(db, owner, "計數器自檢")
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        assert len(count_sql) > 0, "計數器沒抓到任何 SQL——工具本身壞了"

    async def test_現況_清單查詢次數不隨課程數成長(self, client, db, count_sql):
        """基準線：3 門課與 9 門課送出的 SQL 次數相同。

        ⚠️ ⛔ **不斷言「等於某個數字」**：絕對值會在任何人加一次無關查詢時變紅，於是下一個
        人把數字改大——守門就退化成「記錄現況」。要守的是 N+1 的定義本身：**不隨筆數成長**。
        """
        owner = await _user(db, "QC2")
        for i in range(3):
            await _course(db, owner, f"基準小-{i}")
        await db.commit()

        count_sql.clear()
        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        n_small = len(count_sql)

        for i in range(6):
            await _course(db, owner, f"基準大-{i}")
        await db.commit()

        count_sql.clear()
        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        assert len(res.json()["data"]) == 9
        n_large = len(count_sql)

        assert n_large == n_small, f"查詢次數隨筆數成長（3 門 {n_small} 次 → 9 門 {n_large} 次）＝ N+1"


class TestOwnerCardReadsStage:
    """擁有者的卡片讀暫存版（AC 1、2、4、5）。

    把 `course/service.py` 的 `get` 既有規則延伸到清單：**只有擁有者看得到暫存版本**。
    """

    async def test_已關閉課程擁有者的卡片顯示暫存版的課名與章節數(self, client, db):
        owner = await _user(db, "ST1")
        cid = await _course(db, owner, "關閉前的課名", status=COURSE_CLOSED)
        await _chapter(db, cid, "活表章節", 1)
        await _staged_course(db, cid, course_name="編輯後的課名", chapters=3)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["course_name"] == "編輯後的課名"
        assert card["chapter_count"] == 3

    async def test_他人的卡片不受暫存影響(self, client, db):
        """正向錨點（AC 2）。

        ⛔ 管理者**不是**例外——他看到的也該是已生效版本，與詳細頁一致。
        """
        owner = await _user(db, "ST2")
        other = await _user(db, "ST2B")
        cid = await _course(db, owner, "關閉前的課名", status=COURSE_PUBLISHED, days_from_now=30)
        await _chapter(db, cid, "活表章節", 1)
        await _staged_course(db, cid, course_name="編輯後的課名", chapters=5)
        await db.commit()

        res = await client.get(_URL, params={"scope": "all", "page": 1, "limit": 12}, headers=_bearer(other))
        assert res.status_code == 200
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["course_name"] == "關閉前的課名", "他人看到的必須是已生效版本"
        assert card["chapter_count"] == 1

    async def test_已發布課程有暫存時卡片同樣換邊(self, client, db):
        """AC 4：換邊的條件是「有暫存」，不是「已關閉」。"""
        owner = await _user(db, "ST3")
        cid = await _course(db, owner, "發布時的課名", status=COURSE_PUBLISHED, days_from_now=30)
        await _staged_course(db, cid, course_name="編輯後的課名", chapters=2)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["course_name"] == "編輯後的課名"

    async def test_沒有暫存的課程卡片仍讀活表(self, client, db):
        """正向錨點（AC 5）。

        ⚠️ 理由**不是**詳細頁那條「暫存列還不存在，而前端要用 VERSION 做樂觀鎖」——
        `CourseCard` 根本沒有 `version` 欄位（13 個欄位逐一確認過，#813 規劃第 15 節）。
        真正的理由是**沒有暫存列就沒有東西可讀**，此時活表是唯一且正確的來源。
        """
        owner = await _user(db, "ST4")
        cid = await _course(db, owner, "沒編輯過的課", status=COURSE_CLOSED)
        await _chapter(db, cid, "活表章節", 1)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["course_name"] == "沒編輯過的課"
        assert card["chapter_count"] == 1

    async def test_草稿課程不換邊(self, client, db):
        """草稿直接寫活表（#631 只把已發布／已關閉改成暫存），`is_staged` 為假。"""
        from app.et.constants import COURSE_DRAFT

        owner = await _user(db, "ST5")
        cid = await _course(db, owner, "草稿課名", status=COURSE_DRAFT)
        await _staged_course(db, cid, course_name="不該被讀到", chapters=9)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["course_name"] == "草稿課名"


class TestRulingGuards:
    """兩條 SA 裁示的守門（2026-10-27）。

    🔴 這兩個組合**看起來像 bug**，所以必須有測試釘住——否則日後會被「修掉」。
    """

    async def test_卡片狀態仍標已關閉但起訖顯示暫存值(self, client, db):
        """Q1 裁示採 A：`status` / `is_closed` 讀活表，其餘換邊。

        於是一門「已關閉、暫存裡改成遠未來」的課程，卡片會同時顯示「已關閉」與未來的
        起訖——**兩者都正確**：課程確實還沒重開（要按「更新並重開課」），而那個起訖是
        **即將生效的**值。編輯頁也是這樣顯示，正是本 issue 要達成的一致。
        """
        owner = await _user(db, "RG1")
        cid = await _course(db, owner, "已關閉的課", status=COURSE_CLOSED)
        await _staged_course(db, cid, course_name="已關閉的課", chapters=1, open_end_days=400)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["status"] == COURSE_CLOSED, "狀態轉換不走暫存，⛔ 不可換邊"
        assert card["is_closed"] is True
        assert card["open_end_at"] is not None and card["open_end_at"] > utcnow().isoformat(), (
            "起訖應顯示暫存版的未來值"
        )

    async def test_暫存章節全刪光時卡片顯示零章節(self, client, db):
        """Q2 裁示採 A。

        🔴 `has_stage` **刻意不濾 `DELETED`**（濾了會讓「章節全刪光 → 暫存樹變空 → 退回讀
        活表 → 剛刪掉的章節全部復活」），而**章節數要濾**。兩個判準不同是刻意的。

        ⛔ 不可為了「統一」把兩者合併——那會讓卡片顯示「3 章節」、點進去是空的。
        """
        owner = await _user(db, "RG2")
        cid = await _course(db, owner, "刪光章節的課", status=COURSE_CLOSED)
        for i in range(3):
            await _chapter(db, cid, f"活表章節{i}", i)
        await _staged_course(db, cid, course_name="刪光章節的課", chapters=0, deleted_chapters=3)
        await db.commit()

        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        card = next(c for c in res.json()["data"] if c["course_id"] == cid)
        assert card["chapter_count"] == 0, "暫存裡刪光了就是 0，⛔ 不可退回顯示活表的 3"


class TestNoNPlusOne:
    """🔴 AC 6：清單查詢**不產生 N+1**——以查詢次數斷言，不是只驗結果正確。

    `TestQueryCountBaseline` 量的是**沒有暫存**的情形；本組量的是**每一門都有暫存**的
    情形——換邊路徑才是本案新增查詢的地方，也才是會寫成 N+1 的地方。
    """

    async def test_全部課程都有暫存時查詢次數仍不隨筆數成長(self, client, db, count_sql):
        """⛔ 不斷言「等於某個數字」，理由見檔頭。

        ⚠️ 兩次量測都用**同一個 `limit`**：若讓第二次多回幾筆，`paginate` 自己的成本就
        混進來了，測到的不再只是換邊路徑。
        """
        owner = await _user(db, "NP1")
        for i in range(3):
            cid = await _course(db, owner, f"小-{i}", status=COURSE_CLOSED)
            await _staged_course(db, cid, course_name=f"暫存小-{i}", chapters=2)
        await db.commit()

        count_sql.clear()
        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        n_small = len(count_sql)

        for i in range(6):
            cid = await _course(db, owner, f"大-{i}", status=COURSE_CLOSED)
            await _staged_course(db, cid, course_name=f"暫存大-{i}", chapters=2)
        await db.commit()

        count_sql.clear()
        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 9
        assert all(c["course_name"].startswith("暫存") for c in data), "前置條件：每門都該換邊"
        n_large = len(count_sql)

        assert n_large == n_small, (
            f"查詢次數隨筆數成長（3 門有暫存 {n_small} 次 → 9 門 {n_large} 次）＝ N+1。"
            "⚠️ 最可能的成因是逐門呼叫 has_stage 或逐門取暫存樹。"
        )

    async def test_混合有無暫存時同樣不成長(self, client, db, count_sql):
        """半數有暫存、半數沒有——換邊是逐張卡片判定的，混合情形最接近真實清單。"""
        owner = await _user(db, "NP2")
        for i in range(2):
            cid = await _course(db, owner, f"混小有-{i}", status=COURSE_CLOSED)
            await _staged_course(db, cid, course_name=f"暫存混小-{i}", chapters=1)
            await _course(db, owner, f"混小無-{i}", status=COURSE_CLOSED)
        await db.commit()

        count_sql.clear()
        await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        n_small = len(count_sql)

        for i in range(3):
            cid = await _course(db, owner, f"混大有-{i}", status=COURSE_CLOSED)
            await _staged_course(db, cid, course_name=f"暫存混大-{i}", chapters=1)
            await _course(db, owner, f"混大無-{i}", status=COURSE_CLOSED)
        await db.commit()

        count_sql.clear()
        res = await client.get(_URL, params={"scope": "mine", "page": 1, "limit": 12}, headers=_bearer(owner))
        assert len(res.json()["data"]) == 10
        assert len(count_sql) == n_small
