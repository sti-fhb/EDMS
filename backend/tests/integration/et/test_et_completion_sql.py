"""共用完課 SQL 片段 `progress/completion_sql.completed_pairs()`（#464）。

## 為何這組非得是 integration

這支片段是 `enrollment/rules.is_course_completed(done, total)` 的 **SQL 版**。兩者必須對
同一組事實給出相同答案——否則 ET04 列出的「通過」與學員畫面上的「已完課」會對不上，
而兩邊各自的測試都會是綠的。

那個「相同」只能在真 DB 上驗：SQL 版的正確性取決於 `GROUP BY`、JOIN 回 `ET_ITEM` /
`ET_CHAPTER` 過濾軟刪除、以及 `total > 0` 的守門，三者都不是純函式能代驗的。

## 檢核的邊界

| 情境 | `(done, total)` | 預期 | 為何值得一條 |
|---|---|---|---|
| 沒有任何項目的課程 | `(0, 0)` | 未完課 | 字面上是 vacuous truth；`total > 0` 守門擋下 |
| 一項都沒做 | `(0, N)` | 未完課 | 基本 |
| 做了部分 | `(K<N, N)` | 未完課 | 基本 |
| 全部做完 | `(N, N)` | **完課** | 基本 |
| 未完成的項目被刪掉 | `(K, K)` | **完課** | 完課不只由進度寫入觸發 |
| 已完成的項目被刪掉 | 進度列也被連帶軟刪 | 不計入 | 軟刪除防禦 |
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import COMPLETION_NOT_STARTED, COURSE_PUBLISHED, ITEM_MATERIAL, SOURCE_INVITATION_CODE
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.enrollment.rules import is_course_completed
from app.et.material.models import EtMaterial
from app.et.progress.completion_sql import completed_pairs
from app.et.progress.models import EtEnrollment, EtProgress

pytestmark = pytest.mark.integration


async def _user(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id.lower()}@edms.local",
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
    await db.flush()
    return user_id


async def _course(db, *, owner: str) -> int:
    now = utcnow()
    course = EtCourse(
        course_name="完課判定測試",
        status=COURSE_PUBLISHED,
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


async def _items(db, course_id: int, n: int) -> list[int]:
    """建一章 n 項教材。"""
    now = utcnow()
    ch = EtChapter(
        course_id=course_id,
        chapter_name="第一章",
        sort_order=1,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(ch)
    await db.flush()
    ids = []
    for i in range(n):
        material = EtMaterial(material_name=f"教材{i}", version=0, created_user="admin01", created_date=now, deleted=0)
        db.add(material)
        await db.flush()
        item = EtItem(
            chapter_id=ch.chapter_id,
            item_type=ITEM_MATERIAL,
            sort_order=i + 1,
            material_id=material.material_id,
            version=0,
            created_user="admin01",
            created_date=now,
            deleted=0,
        )
        db.add(item)
        await db.flush()
        ids.append(item.item_id)
    return ids


async def _enroll(db, user_id: str, course_id: int) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status=COMPLETION_NOT_STARTED,
            is_removed=False,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _complete(db, user_id: str, course_id: int, item_ids: list[int]) -> None:
    now = utcnow()
    for item_id in item_ids:
        db.add(
            EtProgress(
                user_id=user_id,
                course_id=course_id,
                item_id=item_id,
                is_completed=True,
                created_user=user_id,
                created_date=now,
                deleted=0,
            )
        )
    await db.flush()


async def _is_in_pairs(db, course_id: int, user_id: str) -> bool:
    pairs = completed_pairs(course_id=course_id)
    row = await db.scalar(select(pairs.c.user_id).where(pairs.c.course_id == course_id, pairs.c.user_id == user_id))
    return row is not None


class TestAgreesWithPythonRule:
    """🔴 SQL 版與 `is_course_completed(done, total)` 對同一組事實必須給出相同答案。

    ⚠️ 每一條都同時斷言兩者——只斷言 SQL 版的話，日後有人改了 Python 版（例如把
    `>=` 改成 `>`），SQL 版的測試照樣綠，而兩個畫面從此對不上。
    """

    @pytest.mark.parametrize(("n_items", "n_done"), [(1, 0), (3, 0), (3, 1), (3, 2), (3, 3), (1, 1)])
    async def test_項目數與完成數的各種組合(self, db, n_items: int, n_done: int) -> None:
        owner = await _user(db, f"CS_T{n_items}{n_done}")
        student = await _user(db, f"CS_S{n_items}{n_done}")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, n_items)
        await _enroll(db, student, cid)
        await _complete(db, student, cid, items[:n_done])

        expected = is_course_completed(done=n_done, total=n_items)
        assert await _is_in_pairs(db, cid, student) is expected, (
            f"SQL 版與 Python 版不一致：(done={n_done}, total={n_items}) Python 說 {expected}"
        )

    async def test_沒有任何項目的課程不算完課(self, db) -> None:
        """`(0, 0)`：字面上是 vacuous truth，但那會讓學員一加入就被當成通過。

        ⚠️ **本條驗的是行為，不是 `total > 0` 那道守門。** 2026-09-30 變異檢查實測：拿掉
        那道守門，本條照樣綠——擋下空課程的其實是 `totals` 子查詢的**內連接**（零項目的課程
        不會產生那一組）。那道守門今天是 no-op，只在 `totals` 被改寫成會產生 `total = 0`
        的形狀時才承重，見 `completion_sql.py` 的註解。

        ⛔ 別因為「拿掉守門還是綠」就把本條當成無用而刪掉——它守的是**結果**（空課程不得
        算完課），不論是哪一層在擋。
        """
        owner = await _user(db, "CS_T00")
        student = await _user(db, "CS_S00")
        cid = await _course(db, owner=owner)
        await _enroll(db, student, cid)

        assert is_course_completed(done=0, total=0) is False
        assert await _is_in_pairs(db, cid, student) is False


class TestSoftDelete:
    async def test_未完成的項目被刪掉後即完課(self, db) -> None:
        """⭐ 完課**不只由進度寫入觸發**——學員 2/3，教師刪掉剩下那一項 → 2/2。

        這條釘住的是 SQL 片段的行為；`COMPLETED_AT` 在這個時點要不要寫入是另一件事
        （見 `test_et_completed_at.py`）。
        """
        owner = await _user(db, "CS_TD1")
        student = await _user(db, "CS_SD1")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 3)
        await _enroll(db, student, cid)
        await _complete(db, student, cid, items[:2])
        assert await _is_in_pairs(db, cid, student) is False

        await db.execute(update(EtItem).where(EtItem.item_id == items[2]).values(deleted=1))
        await db.flush()
        assert await _is_in_pairs(db, cid, student) is True

    async def test_已刪除項目的完成紀錄不計入(self, db) -> None:
        """防禦：即使進度列沒被連帶軟刪，JOIN 回 `ET_ITEM` 也要把它濾掉。

        ⚠️ 正常路徑下 `EtItemRepository.soft_delete_with_cascade` 會一併軟刪 `ET_PROGRESS`，
        所以這裡**刻意只刪項目、不刪進度**，製造「進度列殘留」的狀態——那是 cascade
        若被改壞時會出現的資料。少了這層，分子沒縮小、分母縮小，完課會被高估。
        """
        owner = await _user(db, "CS_TD2")
        student = await _user(db, "CS_SD2")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 3)
        await _enroll(db, student, cid)
        # 完成第 0、1 項；刪掉第 1 項但**不刪**其進度列 → 實際完成 1 / 剩 2 項
        await _complete(db, student, cid, items[:2])
        await db.execute(update(EtItem).where(EtItem.item_id == items[1]).values(deleted=1))
        await db.flush()

        assert await _is_in_pairs(db, cid, student) is False, "已刪除項目的完成紀錄不得計入分子"


class TestFilters:
    async def test_依學員過濾(self, db) -> None:
        owner = await _user(db, "CS_TF1")
        a = await _user(db, "CS_SFA")
        b = await _user(db, "CS_SFB")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        for s in (a, b):
            await _enroll(db, s, cid)
            await _complete(db, s, cid, items)

        pairs = completed_pairs(course_id=cid, user_ids=[a])
        users = set(await db.scalars(select(pairs.c.user_id)))
        assert users == {a}
