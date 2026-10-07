"""ET04 改為「受訓完成狀況」（#464）——不需核可課程完課即通過。

## 裁示（2026-09-30，見 #464 的 SA Q 留言）

「通過」有兩種成立方式，**畫面上不分辨**：

| 課程 | 通過的條件 | 通過時間 |
|---|---|---|
| `REQUIRE_APPROVAL = true` | `RESULT = PASS` 且未撤銷（**維持現狀**）| `APPROVED_AT` |
| `REQUIRE_APPROVAL = false` | 全部項目完成 | `ET_ENROLLMENT.COMPLETED_AT` |

- 需核可但**尚未核可**者不列（Q2 A）
- 教師對完課列的可見範圍＝全部課程（Q1 A，與「通過且未撤銷」同側）
- 學員自查側一併納入（Q4 A）
- 排序保留時間：`通過時間 DESC NULLS LAST`

## 與 `test_et_approval_query.py` 的分工

那支的 fixture **全部是 `require_approval=True`**——它的五十餘條測試就是「需核可課程行為
完全一致」（AC 2）最強的護欄，本 issue **一條都不得改**。本檔只驗新增的那一側，以及兩側
共存時的互動（篩選、排序、重複）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.approval.models import EtApproval
from app.et.constants import (
    APPROVAL_FAIL,
    APPROVAL_PASS,
    COMPLETION_NOT_STARTED,
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
from app.et.progress.repository import EtProgressRepository
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_QUERY = "/api/et/approvals/search"
_MINE = "/api/et/approvals/mine"
_FILTER = "/api/et/approvals/filter-courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, roles: tuple[str, ...] = (ROLE_TEACHER,), name: str | None = None) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id.lower()}@edms.local",
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


async def _course(db, *, owner: str, name: str, require_approval: bool) -> int:
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=COURSE_PUBLISHED,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=now + timedelta(days=30),
        version=0,
        require_approval=require_approval,
        urgent_remind_sent=False,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    return course.course_id


async def _items(db, course_id: int, n: int = 1) -> list[int]:
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
        m = EtMaterial(material_name=f"教材{i}", version=0, created_user="admin01", created_date=now, deleted=0)
        db.add(m)
        await db.flush()
        item = EtItem(
            chapter_id=ch.chapter_id,
            item_type=ITEM_MATERIAL,
            sort_order=i + 1,
            material_id=m.material_id,
            version=0,
            created_user="admin01",
            created_date=now,
            deleted=0,
        )
        db.add(item)
        await db.flush()
        ids.append(item.item_id)
    return ids


async def _enroll(db, user_id: str, course_id: int, *, removed: bool = False) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status=COMPLETION_NOT_STARTED,
            is_removed=removed,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _finish(db, user_id: str, course_id: int, item_ids: list[int], *, stamp: bool = True) -> None:
    """完成全部項目。

    `stamp=True` 走真的寫入路徑（會寫 `COMPLETED_AT`）；`False` 直接寫進度列，模擬**活化
    之前就已完課**的既有資料——那種資料的 `COMPLETED_AT` 是 `NULL`。
    """
    if stamp:
        repo = EtProgressRepository()
        for item_id in item_ids:
            await repo.set_item_completed(
                db,
                user_id=user_id,
                course_id=course_id,
                item_id=item_id,
                completed=True,
                operator=OperatorInfo(user_id),
            )
        return
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


async def _approve(db, *, course_id: int, user_id: str, result: str, by: str, revoked: bool = False) -> None:
    now = utcnow()
    db.add(
        EtApproval(
            course_id=course_id,
            user_id=user_id,
            result=result,
            result_note=None,
            is_revoked=revoked,
            revoke_reason="誤植" if revoked else None,
            approved_by=by,
            approved_at=now,
            revoked_by=by if revoked else None,
            revoked_at=now if revoked else None,
            version=0,
            created_user=by,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


def _rows(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _pairs(rows: list[dict]) -> set[tuple[str, str]]:
    return {(row["user_name"], row["course_name"]) for row in rows}


class TestCompletionCountsAsPass:
    async def test_不需核可課程完課即列為通過(self, client, db) -> None:
        """AC 1——本 issue 的本體。"""
        t = await _user(db, "TC_T1")
        s = await _user(db, "TC_S1", roles=(ROLE_STUDENT,), name="林完課")
        cid = await _course(db, owner=t, name="線上自學課", require_approval=False)
        items = await _items(db, cid, 2)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))
        assert [(r["user_name"], r["result"]) for r in rows] == [("林完課", APPROVAL_PASS)]

    async def test_不需核可但未完課者不出現(self, client, db) -> None:
        t = await _user(db, "TC_T2")
        s = await _user(db, "TC_S2", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="未完課", require_approval=False)
        items = await _items(db, cid, 2)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items[:1])

        assert _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t))) == []

    async def test_需核可課程已完課未核可者不出現(self, client, db) -> None:
        """🔴 Q2 裁示 A 的紅線——需核可的課程，**核可過才算通過**。

        ⚠️ 這條同時是本 issue 留下的已知假陰性：查的人看到「查無」會讀成「他沒受訓」，
        而他其實已做完線上部分、只差教師簽。那是裁示的已知後果，記錄於 #464。
        """
        t = await _user(db, "TC_T3")
        s = await _user(db, "TC_S3", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="需核可", require_approval=True)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        assert _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t))) == []

    async def test_完課列的通過時間取自完課時間(self, client, db) -> None:
        t = await _user(db, "TC_T4")
        s = await _user(db, "TC_S4", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="有時間", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))
        assert rows[0]["approved_at"] is not None, "活化之後的完課必須有通過時間"

    async def test_完課列沒有核可人與備註(self, client, db) -> None:
        """不需核可的課程**事實上沒有核可者**——回 `null`，不是遮蔽、也不是忘了填。"""
        t = await _user(db, "TC_T5")
        s = await _user(db, "TC_S5", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="無核可人", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        row = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))[0]
        assert row["approved_by_name"] is None
        assert row["result_note"] is None
        assert row["is_revoked"] is False

    async def test_已移除學員的完課仍列出(self, client, db) -> None:
        """SD 自決（#464 撤回紀錄）：完課是歷史事實，與已移除者的核可紀錄照列一致。"""
        t = await _user(db, "TC_T6")
        s = await _user(db, "TC_S6", roles=(ROLE_STUDENT,), name="已移除者")
        cid = await _course(db, owner=t, name="移除", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid, removed=True)
        await _finish(db, s, cid, items, stamp=False)

        rows = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))
        assert [r["user_name"] for r in rows] == ["已移除者"]

    async def test_關鍵字對完課列同樣生效(self, client, db) -> None:
        t = await _user(db, "TC_T7")
        hit = await _user(db, "TC_S7A", roles=(ROLE_STUDENT,), name="王命中")
        miss = await _user(db, "TC_S7B", roles=(ROLE_STUDENT,), name="李不中")
        cid = await _course(db, owner=t, name="關鍵字", require_approval=False)
        items = await _items(db, cid, 1)
        for s in (hit, miss):
            await _enroll(db, s, cid)
            await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"keyword": "王命中"}, headers=_bearer(t)))
        assert [r["user_name"] for r in rows] == ["王命中"]


class TestCoexistence:
    """兩種來源共存時的互動——篩選、排序、重複。"""

    async def test_篩僅通過時完課列仍在(self, client, db) -> None:
        """🔴 完課**就是**通過（Q3 裁示）。若把 `RESULT = 'PASS'` 直接套在聯集上，完課列
        沒有 `RESULT` 欄而被全數濾掉——症狀是「選了僅通過反而少了一半資料」，且**不選篩選
        時完全正常**。"""
        t = await _user(db, "TC_T8")
        s = await _user(db, "TC_S8", roles=(ROLE_STUDENT,), name="甲")
        cid = await _course(db, owner=t, name="自學", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"course_id": cid, "result": APPROVAL_PASS}, headers=_bearer(t)))
        assert [r["user_name"] for r in rows] == ["甲"]

    async def test_篩僅不通過時完課列不在(self, client, db) -> None:
        t = await _user(db, "TC_T9")
        s = await _user(db, "TC_S9", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="自學", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"course_id": cid, "result": APPROVAL_FAIL}, headers=_bearer(t)))
        assert rows == []

    async def test_聯集後總筆數與實際列數一致(self, client, db) -> None:
        """釘住「不得後篩」：`meta.total` 必須與可翻頁的列數同源。"""
        t = await _user(db, "TC_TA")
        s = await _user(db, "TC_SA", roles=(ROLE_STUDENT,), name="雙源")
        approval_c = await _course(db, owner=t, name="需核可課", require_approval=True)
        self_c = await _course(db, owner=t, name="自學課", require_approval=False)
        items = await _items(db, self_c, 1)
        await _enroll(db, s, self_c)
        await _finish(db, s, self_c, items)
        await _approve(db, course_id=approval_c, user_id=s, result=APPROVAL_PASS, by=t)

        body = (await client.post(_QUERY, json={"keyword": "雙源"}, headers=_bearer(t))).json()
        assert body["meta"]["total"] == len(body["data"]) == 2
        assert _pairs(body["data"]) == {("雙源", "需核可課"), ("雙源", "自學課")}

    async def test_通過時間為空者排在最後(self, client, db) -> None:
        """🔴 PostgreSQL 的 `DESC` **預設 NULLS FIRST**——不明寫的話，活化前就已完課的
        既有資料（`COMPLETED_AT IS NULL`）會**全部浮到最上面**。正式機從頭建不會有這種資料，
        但**測試環境會**，而手測就在那裡做。"""
        t = await _user(db, "TC_TB")
        s = await _user(db, "TC_SB", roles=(ROLE_STUDENT,), name="排序")
        legacy = await _course(db, owner=t, name="既有完課", require_approval=False)
        approved = await _course(db, owner=t, name="有核可", require_approval=True)
        items = await _items(db, legacy, 1)
        await _enroll(db, s, legacy)
        await _finish(db, s, legacy, items, stamp=False)  # COMPLETED_AT 留空
        await _approve(db, course_id=approved, user_id=s, result=APPROVAL_PASS, by=t)

        rows = _rows(await client.post(_QUERY, json={"keyword": "排序"}, headers=_bearer(t)))
        assert [r["course_name"] for r in rows] == ["有核可", "既有完課"]
        assert rows[-1]["approved_at"] is None

    async def test_切換為不需核可後同一人不出現兩列(self, client, db) -> None:
        """🔴 `REQUIRE_APPROVAL` **發布後仍可切換**（`course/service.update_basic` 無狀態守門）。

        一門課先需核可、核可了某人、之後切成不需核可 → 核可側列出他的核可紀錄，完課側又
        列出同一人的完課。處置：**有核可紀錄者以核可紀錄為準**——教師的明確判斷（含不通過
        與撤銷）不該被事後切一個勾選框就靜默覆蓋。
        """
        t = await _user(db, "TC_TC")
        s = await _user(db, "TC_SC", roles=(ROLE_STUDENT,), name="切換")
        cid = await _course(db, owner=t, name="切換課", require_approval=True)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)
        await _approve(db, course_id=cid, user_id=s, result=APPROVAL_PASS, by=t)
        await db.execute(update(EtCourse).where(EtCourse.course_id == cid).values(require_approval=False))
        await db.flush()

        rows = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))
        assert len(rows) == 1, f"同一人同一課只能有一列，實得 {len(rows)}"
        assert rows[0]["approved_by_name"] is not None, "應以核可紀錄為準"

    async def test_切換後被評為不通過者不會因完課而翻成通過(self, client, db) -> None:
        """上一條的另一半：明確的 FAIL 不得被自動規則覆蓋。"""
        t = await _user(db, "TC_TD")
        s = await _user(db, "TC_SD", roles=(ROLE_STUDENT,), name="不通過")
        cid = await _course(db, owner=t, name="切換課2", require_approval=True)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)
        await _approve(db, course_id=cid, user_id=s, result=APPROVAL_FAIL, by=t)
        await db.execute(update(EtCourse).where(EtCourse.course_id == cid).values(require_approval=False))
        await db.flush()

        rows = _rows(await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(t)))
        assert [r["result"] for r in rows] == [APPROVAL_FAIL]

    async def test_逐頁翻完不重複也不漏列(self, client, db) -> None:
        """核可列與完課列混合、`limit` 小於總數時，逐頁串起來必須恰好是全集。

        排序鍵 `通過時間 DESC NULLS LAST, approval_id DESC NULLS LAST, course_id, user_id`
        必須**決定性**——否則同一時間戳的多列在兩次查詢間順序不同，翻頁時就會重複或漏列，
        而每一頁單獨看都正常。⚠️ 刻意混一筆 `COMPLETED_AT IS NULL` 的完課，讓 NULL 也進到
        排序比較裡。
        """
        t = await _user(db, "TC_TP")
        s = await _user(db, "TC_SP", roles=(ROLE_STUDENT,), name="翻頁")
        expected = set()
        for i in range(2):
            cid = await _course(db, owner=t, name=f"需核可{i}", require_approval=True)
            await _approve(db, course_id=cid, user_id=s, result=APPROVAL_PASS, by=t)
            expected.add(f"需核可{i}")
        for i, stamp in enumerate((True, False)):
            cid = await _course(db, owner=t, name=f"自學{i}", require_approval=False)
            items = await _items(db, cid, 1)
            await _enroll(db, s, cid)
            await _finish(db, s, cid, items, stamp=stamp)
            expected.add(f"自學{i}")

        seen: list[str] = []
        for page in range(1, 6):
            body = (
                await client.post(_QUERY, json={"keyword": "翻頁", "page": page, "limit": 1}, headers=_bearer(t))
            ).json()
            assert body["meta"]["total"] == 4
            seen += [r["course_name"] for r in body["data"]]
        assert len(seen) == len(set(seen)), f"翻頁出現重複：{seen}"
        assert set(seen) == expected, f"翻頁漏列：預期 {expected}，實得 {set(seen)}"


class TestVisibility:
    async def test_教師看得到他人課程的完課列(self, client, db) -> None:
        """Q1 裁示 A：完課就是通過，與「通過且未撤銷」同側——全部課程可見。"""
        me = await _user(db, "TC_TE1")
        other = await _user(db, "TC_TE2")
        s = await _user(db, "TC_SE", roles=(ROLE_STUDENT,), name="跨課")
        cid = await _course(db, owner=other, name="別人的自學課", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.post(_QUERY, json={"keyword": "跨課"}, headers=_bearer(me)))
        assert _pairs(rows) == {("跨課", "別人的自學課")}

    async def test_教師可依他人的不需核可課程查出完課名單(self, client, db) -> None:
        """↔️ #548 裁示 4 之前，這條斷言的是 403 `ET_APPROVAL_007`。

        完課側是 #464 新增的母體，當時一併套了 #439 的擁有權閘。閘退役後，完課側
        也要跟著開放——**兩側不得有不同的範圍規則**，否則同一次查詢會依課程是否需要
        核可而給出不同的可見範圍，而畫面上看不出那條界線在哪。
        """
        me = await _user(db, "TC_TN1")
        other = await _user(db, "TC_TN2")
        s = await _user(db, "TC_SN", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=other, name="別人的自學課", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        r = await client.post(_QUERY, json={"course_id": cid}, headers=_bearer(me))
        assert r.status_code == 200, r.text
        assert {row["course_name"] for row in r.json()["data"]} == {"別人的自學課"}

    async def test_他人課程的不通過對教師可見(self, client, db) -> None:
        """↔️ 原名「既有分流未被改動」，斷言的是空清單（裁示 C 的結果分流）。

        #548 裁示 1 統一可見範圍後，同一筆應該查得到。⚠️ 它的**備註**仍被遮蔽，
        那一半由 `test_et_approval_query.py::TestResultNoteRedaction` 守。
        """
        me = await _user(db, "TC_TF1")
        other = await _user(db, "TC_TF2")
        s = await _user(db, "TC_SF", roles=(ROLE_STUDENT,), name="分流")
        cid = await _course(db, owner=other, name="別人的需核可課", require_approval=True)
        await _approve(db, course_id=cid, user_id=s, result=APPROVAL_FAIL, by=other)

        rows = _rows(await client.post(_QUERY, json={"keyword": "分流"}, headers=_bearer(me)))
        assert [row["course_name"] for row in rows] == ["別人的需核可課"]


class TestStudentSelfView:
    async def test_學員看得到自己不需核可課程的通過(self, client, db) -> None:
        """Q4 裁示 A——同一個定義，學員側一併納入。"""
        t = await _user(db, "TC_TG")
        s = await _user(db, "TC_SG", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="我的自學課", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        rows = _rows(await client.get(_MINE, headers=_bearer(s)))
        assert [r["course_name"] for r in rows] == ["我的自學課"]
        assert rows[0]["approved_at"] is not None

    async def test_學員看不到自己未完課的不需核可課程(self, client, db) -> None:
        t = await _user(db, "TC_TH")
        s = await _user(db, "TC_SH", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="還沒完", require_approval=False)
        items = await _items(db, cid, 2)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items[:1])

        assert _rows(await client.get(_MINE, headers=_bearer(s))) == []

    async def test_學員側看不到他人的完課(self, client, db) -> None:
        t = await _user(db, "TC_TI")
        me = await _user(db, "TC_SI1", roles=(ROLE_STUDENT,))
        other = await _user(db, "TC_SI2", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="別人完課", require_approval=False)
        items = await _items(db, cid, 1)
        for s in (me, other):
            await _enroll(db, s, cid)
        await _finish(db, other, cid, items)

        assert _rows(await client.get(_MINE, headers=_bearer(me))) == []


class TestFilterCourseOptions:
    async def test_下拉含不需核可但有完課的課程(self, client, db) -> None:
        """否則不需核可的課程**選不到**——而那正是本 issue 要納入的那些。"""
        t = await _user(db, "TC_TJ")
        s = await _user(db, "TC_SJ", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="自學下拉", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        r = await client.get(_FILTER, headers=_bearer(t))
        assert r.status_code == 200, r.text
        assert "自學下拉" in {o["course_name"] for o in r.json()}

    async def test_下拉不含無人完課的不需核可課程(self, client, db) -> None:
        """與既有規則一致：下拉只列**選得出東西**的課程，沒有死選項。"""
        t = await _user(db, "TC_TK")
        await _course(db, owner=t, name="沒人完課", require_approval=False)

        r = await client.get(_FILTER, headers=_bearer(t))
        assert "沒人完課" not in {o["course_name"] for o in r.json()}

    async def test_教師下拉含他人的不需核可課(self, client, db) -> None:
        """↔️ 原本斷言 `not in`（#439 的擁有權限制對完課側同樣成立）。

        裁示 4 之後下拉不分 owner——⚠️ 下拉與查詢的母體必須一致，否則會出現
        「這門課查得到卻選不到」這種無法解釋的狀態。
        """
        me = await _user(db, "TC_TL1")
        other = await _user(db, "TC_TL2")
        s = await _user(db, "TC_SL", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=other, name="別人自學", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        r = await client.get(_FILTER, headers=_bearer(me))
        assert "別人自學" in {o["course_name"] for o in r.json()}

    async def test_管理者下拉含全部(self, client, db) -> None:
        t = await _user(db, "TC_TM")
        adm = await _user(db, "TC_AM", roles=(ROLE_ADMIN,))
        s = await _user(db, "TC_SM", roles=(ROLE_STUDENT,))
        cid = await _course(db, owner=t, name="管理者可見", require_approval=False)
        items = await _items(db, cid, 1)
        await _enroll(db, s, cid)
        await _finish(db, s, cid, items)

        r = await client.get(_FILTER, headers=_bearer(adm))
        assert "管理者可見" in {o["course_name"] for o in r.json()}
