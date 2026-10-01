"""`ET_ENROLLMENT.COMPLETED_AT` 的活化（#464，2026-09-30 裁示）。

## 寫入規則

**第一次完課的當下，且只寫一次**（`COMPLETED_AT IS NULL` 時才寫）。完課回退時**不清除**
——語意是「第一次達成完課的時間」；殘留的值不會被誤讀，因為查詢端以即時判定決定列要不要
出現，未完課者根本不在結果裡。

## 為何掛在 repository 而不是 service

三個進度寫入點中，`quiz/service.py` 直接持有 `EtProgressRepository`、**繞過 progress
service**。掛在 service 層要三處各叫一次，第四個寫入點出現時就會漏。

⚠️ 另外**完課不只由進度寫入觸發**：學員 2/3、教師刪掉剩下那一項 → 2/2 即完課，但那條路
沒經過任何進度寫入。所以項目刪除（`EtItemRepository.soft_delete_with_cascade`）也要掛。

⛔ **不要改用 `MAX(ET_PROGRESS.UPDATED_DATE)` 推導**：`set_item_completed` 的
`on_conflict_do_update` **無條件**寫 `UPDATED_DATE = now`——學員完課後再開一次教材，
那個時間就往後漂。顯示一個會漂移的時間，比留空更糟。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import COMPLETION_NOT_STARTED, COURSE_PUBLISHED, ITEM_MATERIAL, SOURCE_INVITATION_CODE
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.repository import EtItemRepository
from app.et.material.models import EtMaterial
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.progress.repository import EtProgressRepository

pytestmark = pytest.mark.integration

_repo = EtProgressRepository()


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


async def _items(db, course_id: int, n: int, *, chapter_order: int = 1) -> list[int]:
    """建一章 n 項教材。⚠️ 同一課程建第二章時要給不同的 `chapter_order`（唯一鍵 `UX_ET_CHAPTER_COURSE_ORDER`）。"""
    now = utcnow()
    ch = EtChapter(
        course_id=course_id,
        chapter_name=f"第{chapter_order}章",
        sort_order=chapter_order,
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


async def _completed_at(db, user_id: str, course_id: int):
    return await db.scalar(
        select(EtEnrollment.completed_at).where(EtEnrollment.user_id == user_id, EtEnrollment.course_id == course_id)
    )


async def _mark(db, user_id: str, course_id: int, item_id: int, *, completed: bool = True) -> None:
    """走真的寫入路徑（不是直接 `db.add(EtProgress)`）——要驗的正是那條路徑上的掛鉤。"""
    await _repo.set_item_completed(
        db, user_id=user_id, course_id=course_id, item_id=item_id, completed=completed, operator=OperatorInfo(user_id)
    )


class TestStampOnProgressWrite:
    async def test_最後一項完成時寫入完課時間(self, db) -> None:
        owner = await _user(db, "CA_T1")
        student = await _user(db, "CA_S1")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 2)
        await _enroll(db, student, cid)

        await _mark(db, student, cid, items[0])
        assert await _completed_at(db, student, cid) is None, "只完成一半時不得寫入"

        before = utcnow()
        await _mark(db, student, cid, items[1])
        stamped = await _completed_at(db, student, cid)
        assert stamped is not None
        assert stamped >= before

    async def test_只寫一次_再次完成不覆蓋(self, db) -> None:
        """⭐ 這條就是不用 `UPDATED_DATE` 的理由——同一個寫入路徑會被重複呼叫。"""
        owner = await _user(db, "CA_T2")
        student = await _user(db, "CA_S2")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        await _enroll(db, student, cid)

        await _mark(db, student, cid, items[0])
        first = await _completed_at(db, student, cid)
        # ⚠️ 不可省：少了這行，寫入壞掉時兩次都是 None，`None == None` 恆真而本條照樣綠。
        assert first is not None
        await _mark(db, student, cid, items[0])  # 學員完課後再開一次教材
        assert await _completed_at(db, student, cid) == first

    async def test_標記為未完成不會寫入(self, db) -> None:
        owner = await _user(db, "CA_T3")
        student = await _user(db, "CA_S3")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        await _enroll(db, student, cid)

        await _mark(db, student, cid, items[0], completed=False)
        assert await _completed_at(db, student, cid) is None

    async def test_完課回退後不清除(self, db) -> None:
        """教師新增章節 → 完課回退。`COMPLETED_AT` 保留——它是「第一次」達成的時間。"""
        owner = await _user(db, "CA_T4")
        student = await _user(db, "CA_S4")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        await _enroll(db, student, cid)
        await _mark(db, student, cid, items[0])
        first = await _completed_at(db, student, cid)
        assert first is not None  # 同上：否則回退前後都是 None，本條恆真

        await _items(db, cid, 1, chapter_order=2)  # 新增一章一項 → 1/2
        assert await _completed_at(db, student, cid) == first

    async def test_批次寫入也會寫入完課時間(self, db) -> None:
        """`quiz/service` 走 `set_item_completed_bulk` 且**繞過 progress service**——
        掛鉤必須在 repository 層才接得到它。"""
        owner = await _user(db, "CA_T5")
        a = await _user(db, "CA_S5A")
        b = await _user(db, "CA_S5B")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        for s in (a, b):
            await _enroll(db, s, cid)

        await _repo.set_item_completed_bulk(
            db, user_ids=[a, b], course_id=cid, item_id=items[0], completed=True, operator=OperatorInfo(owner)
        )
        assert await _completed_at(db, a, cid) is not None
        assert await _completed_at(db, b, cid) is not None

    async def test_只寫入受影響的那位學員(self, db) -> None:
        owner = await _user(db, "CA_T6")
        done = await _user(db, "CA_S6A")
        other = await _user(db, "CA_S6B")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 1)
        for s in (done, other):
            await _enroll(db, s, cid)

        await _mark(db, done, cid, items[0])
        assert await _completed_at(db, other, cid) is None


class TestStampOnItemDelete:
    async def test_刪除未完成項目使學員完課時寫入(self, db) -> None:
        """⭐ 完課不只由進度寫入觸發——這條路**沒有**經過任何 `set_item_completed`。"""
        owner = await _user(db, "CA_T7")
        student = await _user(db, "CA_S7")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 2)
        await _enroll(db, student, cid)
        await _mark(db, student, cid, items[0])
        assert await _completed_at(db, student, cid) is None

        await EtItemRepository().soft_delete_with_cascade(db, [items[1]], OperatorInfo(owner))
        assert await _completed_at(db, student, cid) is not None

    async def test_刪除項目不影響本來就未完課者(self, db) -> None:
        owner = await _user(db, "CA_T8")
        student = await _user(db, "CA_S8")
        cid = await _course(db, owner=owner)
        items = await _items(db, cid, 3)
        await _enroll(db, student, cid)

        await EtItemRepository().soft_delete_with_cascade(db, [items[2]], OperatorInfo(owner))
        assert await _completed_at(db, student, cid) is None
