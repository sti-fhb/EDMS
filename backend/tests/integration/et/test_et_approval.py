"""ET03 線下考核核可整合測試（US16 / #352）。

此處只驗**需要真 DB 才驗得了**的事：條件式寫入的原子性、唯一鍵、樂觀鎖、跨表的完課
前提、稽核與寄信的實際落地、以及「核可不影響完課統計」這類只有真資料才看得出來的
隔離性。

純推導（四態衍生、撤銷原因必填）於 `tests/unit/et/test_approval_rules.py`；
範本參數 key 於 `tests/unit/et/test_et_approval_mail.py`。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.approval.models import EtApproval
from app.et.constants import (
    APPROVAL_FAIL,
    APPROVAL_PASS,
    COMPLETION_NOT_STARTED,
    COURSE_CLOSED,
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
    name: str = "核可測試課程",
    require_approval: bool = True,
    status: str = COURSE_PUBLISHED,
    open_end_at=None,
) -> int:
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=status,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=open_end_at if open_end_at is not None else now + timedelta(days=30),
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


async def _item(db, course_id: int, *, title: str, order: int = 1) -> int:
    """建一章一項——`ET_ITEM` 的標題在 `ET_MATERIAL` 上，且有 CHECK 強制型別對應。"""
    now = utcnow()
    ch = EtChapter(
        course_id=course_id,
        chapter_name=f"章節{order}",
        sort_order=order,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(ch)
    await db.flush()
    material = EtMaterial(material_name=title, version=0, created_user="admin01", created_date=now, deleted=0)
    db.add(material)
    await db.flush()
    item = EtItem(
        chapter_id=ch.chapter_id,
        item_type=ITEM_MATERIAL,
        sort_order=order,
        material_id=material.material_id,
        version=0,
        created_user="admin01",
        created_date=now,
        deleted=0,
    )
    db.add(item)
    await db.flush()
    return item.item_id


async def _enroll(db, user_id: str, course_id: int, *, removed: bool = False) -> EtEnrollment:
    now = utcnow()
    row = EtEnrollment(
        user_id=user_id,
        course_id=course_id,
        join_source=SOURCE_INVITATION_CODE,
        joined_at=now,
        # 🔴 刻意留在 `NOT_STARTED`：該欄位是死的（只在加入時寫入、無推進路徑）。
        # 任何以它為核可前提的實作，在這些測試裡都會回「未完課」而全數跳過。
        completion_status=COMPLETION_NOT_STARTED,
        is_removed=removed,
        created_user=user_id,
        created_date=now,
        deleted=0,
    )
    db.add(row)
    await db.flush()
    return row


async def _complete(db, user_id: str, course_id: int, item_id: int) -> None:
    now = utcnow()
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


async def _completed_student(db, course_id: int, user_id: str, item_id: int, *, name: str | None = None) -> str:
    """建一位**已完課**的在籍學員（核可的前提）。"""
    await _user(db, user_id, roles=(ROLE_STUDENT,), name=name)
    await _enroll(db, user_id, course_id)
    await _complete(db, user_id, course_id, item_id)
    return user_id


async def _approval_of(db, course_id: int, user_id: str) -> EtApproval | None:
    return await db.scalar(select(EtApproval).where(EtApproval.course_id == course_id, EtApproval.user_id == user_id))


async def _pending_mails(db, template_code: str = "APPROVAL_PASSED") -> list[DpEmailLog]:
    """⚠️ 必須篩 `STATUS='PENDING'`。

    範本 params key 打錯時平台會寫一列 `STATUS='FAILED'` 的空信且**不拋例外**，
    只數列數的斷言會把那種靜默失敗當成成功。
    """
    rows = await db.scalars(
        select(DpEmailLog).where(DpEmailLog.template_code == template_code, DpEmailLog.status == "PENDING")
    )
    return list(rows.all())


class TestApprovalGate:
    """核可的四道前置閘（課程存在 / 有權 / 已啟用 / 未關閉）。"""

    async def test_未啟用線下核可的課程不可核可(self, client, db) -> None:
        """AC 1：`REQUIRE_APPROVAL = false` 時完全沒有核可這回事。"""
        teacher = await _user(db, "t_ap01")
        course_id = await _course(db, owner=teacher, require_approval=False)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap01a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_001"

    async def test_他人課程之教師不可核可(self, client, db) -> None:
        """`FR-ET-US16-07`：非 owner 之其他教師 MUST NOT 核可。"""
        owner = await _user(db, "t_ap02")
        other = await _user(db, "t_ap02b")
        course_id = await _course(db, owner=owner)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap02a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(other),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_管理者可核可他人課程(self, client, db) -> None:
        """SA 裁示 2026-09-17 Q1 = C：後端放寬為 owner ∪ 管理者。

        `spec.md` §角色表與 `FR-ET-US16-07` 都寫「教師（owner）**或管理者**」，而在本
        issue 之前 ET03 全線 owner-only——管理者連別人的課都進不去。
        """
        owner = await _user(db, "t_ap03")
        admin = await _user(db, "a_ap03", roles=(ROLE_ADMIN,))
        course_id = await _course(db, owner=owner)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap03a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(admin),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 200, r.text
        assert r.json()["approved"] == 1
        row = await _approval_of(db, course_id, student)
        assert row is not None and row.approved_by == admin

    async def test_管理者可讀他人課程的ET03學員清單(self, client, db) -> None:
        """Q1 = C 的另一半：核可端點放寬了，讀取端點也得放寬，否則管理者看不到那張表。

        ⚠️ 前端課程下拉仍為 `scope=mine`（裁示明訂留到 US17），所以管理者目前**沒有
        進入路徑**——這是刻意的中間狀態，見 `ensure_owner_or_admin` 的 docstring。
        """
        owner = await _user(db, "t_ap04")
        admin = await _user(db, "a_ap04", roles=(ROLE_ADMIN,))
        course_id = await _course(db, owner=owner)
        item_id = await _item(db, course_id, title="教材")
        await _completed_student(db, course_id, "s_ap04a", item_id, name="王小明")
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(admin))

        assert r.status_code == 200, r.text
        assert [row["user_name"] for row in r.json()["data"]] == ["王小明"]

    async def test_他人課程之教師仍不可讀ET03學員清單(self, client, db) -> None:
        """放寬的只有管理者——US9 對「別的教師」的守門必須原封不動。"""
        owner = await _user(db, "t_ap05")
        other = await _user(db, "t_ap05b")
        course_id = await _course(db, owner=owner)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(other))

        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_手動關閉的課程不可核可(self, client, db) -> None:
        """AC 12 / `FR-ET-US16-10`。"""
        teacher = await _user(db, "t_ap06")
        course_id = await _course(db, owner=teacher, status=COURSE_CLOSED)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap06a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_002"

    async def test_閱課期間已過的課程不可核可(self, client, db) -> None:
        """🔴 **第二種關閉來源**，`STATUS` 仍是 `PUBLISHED`。

        ET-16 的 SCHET002 執行前，期間已過的課程狀態不會自動變成 `CLOSED`。只看
        `STATUS` 的實作會讓教師在一門對學員已經關閉的課程上繼續核可，而且測試全綠。
        比照 ET-12 差異 3 的兩種來源各留一條。
        """
        teacher = await _user(db, "t_ap07")
        course_id = await _course(db, owner=teacher, open_end_at=utcnow() - timedelta(days=1))
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap07a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_002"

    async def test_關閉期間仍可閱覽核可狀態(self, client, db) -> None:
        """AC 12 的另一半：關閉是「讀照舊、寫全停」，不是整頁擋掉。"""
        teacher = await _user(db, "t_ap08")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap08a", item_id, name="已核可的")
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.json()["data"][0]["approval_status"] == "PASSED"

    async def test_再開課後恢復可核可(self, client, db) -> None:
        """AC 12 的第三段：「再開課後恢復」。

        關閉的判定是**即時計算**的（`is_effectively_closed`），沒有任何地方存下
        「這門課被擋過」的狀態，所以恢復是自動的。這條測試釘的正是這件事——若日後
        有人把關閉判定改成讀某個持久化旗標，恢復就會失效而其他測試全綠。
        """
        teacher = await _user(db, "t_ap09")
        course_id = await _course(db, owner=teacher, open_end_at=utcnow() - timedelta(days=1))
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap09a", item_id)
        await db.commit()
        blocked = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        assert blocked.status_code == 409

        # 再開課＝重設一組新的起訖時間（`FR-ET-US11-09`）
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == course_id)
            .values(status=COURSE_PUBLISHED, open_end_at=utcnow() + timedelta(days=30))
        )
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 200, r.text
        assert r.json()["approved"] == 1

    async def test_管理者仍不可重置重考次數或移除學員(self, client, db) -> None:
        """🚨 釘住「刻意不放寬」的邊界。

        SA 裁示 Q1 = C 只放寬**讀取**端點與核可 / 撤銷；重置重考次數與移除學員是 US9 的
        課程管理動作，不在 US16 的裁示範圍內，仍走 `_require_writable` → `ensure_owner`。

        目前行為正確是因為那條路徑根本沒被本 issue 觸及——但「沒改到」不是保證。少了這
        一條，日後有人把 `_require_writable` 也換成 `ensure_owner_or_admin`（看起來很像
        一致性修正）不會有任何測試變紅。
        """
        owner = await _user(db, "t_ap15")
        admin = await _user(db, "a_ap15", roles=(ROLE_ADMIN,))
        course_id = await _course(db, owner=owner)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap15a", item_id)
        await db.commit()

        removed = await client.delete(f"{_URL}/{course_id}/students/{student}", headers=_bearer(admin))

        assert removed.status_code == 403, removed.text
        assert removed.json()["error_code"] == "ET_COURSE_002"


class TestApproveWrite:
    """核可的寫入（AC 3）。"""

    async def test_核可通過寫入紀錄(self, client, db) -> None:
        teacher = await _user(db, "t_ap10")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap10a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.status_code == 200, r.text
        assert r.json() == {"approved": 1, "skipped": []}
        row = await _approval_of(db, course_id, student)
        assert row is not None
        assert row.result == APPROVAL_PASS
        assert row.is_revoked is False
        assert row.approved_by == teacher
        assert row.approved_at is not None
        assert row.version == 1

    async def test_不通過可填備註且留紀錄(self, client, db) -> None:
        """`FR-ET-US16-04`：FAIL **留紀錄**、得附 `RESULT_NOTE`，不是回到待核可。"""
        teacher = await _user(db, "t_ap11")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap11a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_FAIL, "result_note": "實機操作未達標準"},
        )

        assert r.status_code == 200, r.text
        row = await _approval_of(db, course_id, student)
        assert row is not None
        assert row.result == APPROVAL_FAIL
        assert row.result_note == "實機操作未達標準"

    async def test_未完課者被跳過(self, client, db) -> None:
        """`FR-ET-US16-03`。回 200 + `skipped`，前端單筆顯示 `ET-MSG-ET03-304`。"""
        teacher = await _user(db, "t_ap12")
        course_id = await _course(db, owner=teacher)
        await _item(db, course_id, title="教材")  # 有項目但學員沒完成
        await _user(db, "s_ap12a", roles=(ROLE_STUDENT,))
        await _enroll(db, "s_ap12a", course_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": ["s_ap12a"], "result": APPROVAL_PASS},
        )

        assert r.status_code == 200, r.text
        assert r.json() == {"approved": 0, "skipped": [{"user_id": "s_ap12a", "reason": "NOT_COMPLETED"}]}
        assert await _approval_of(db, course_id, "s_ap12a") is None

    async def test_完課判定用計數而非四捨五入的百分比(self, client, db) -> None:
        """🔴 201 個項目完成 200 個時 `completion_pct` 回 100。

        用百分比判定會讓最後一項還沒完成就開放核可，而**畫面上完全看不出哪裡不對**
        ——`is_course_completed` 刻意收 `(done, total)` 就是為了這件事。此處用 3 項
        完成 2 項；比例 67% 不會誤判，但若有人寫成 `>= total - 1` 之類的寬鬆條件就會紅。
        """
        teacher = await _user(db, "t_ap13")
        course_id = await _course(db, owner=teacher)
        items = [await _item(db, course_id, title=f"教材{i}", order=i) for i in (1, 2, 3)]
        await _user(db, "s_ap13a", roles=(ROLE_STUDENT,))
        await _enroll(db, "s_ap13a", course_id)
        await _complete(db, "s_ap13a", course_id, items[0])
        await _complete(db, "s_ap13a", course_id, items[1])
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": ["s_ap13a"], "result": APPROVAL_PASS},
        )

        assert r.json()["skipped"] == [{"user_id": "s_ap13a", "reason": "NOT_COMPLETED"}]

    async def test_已移除學員不可被核可(self, client, db) -> None:
        """🔴 完課計數**不濾在籍**——它數 `ET_PROGRESS` 的列，而移除走 `IS_REMOVED`、
        學習歷史刻意保留。

        少了在籍閘，一位「曾完課、之後被移除」的學員會被建立核可列，而他在 US17 核可
        查詢裡查得到自己「已通過」一門早就被移出的課。
        """
        teacher = await _user(db, "t_ap14")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        await _user(db, "s_ap14a", roles=(ROLE_STUDENT,))
        await _enroll(db, "s_ap14a", course_id, removed=True)
        await _complete(db, "s_ap14a", course_id, item_id)  # 移除前已完課，歷史留著
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": ["s_ap14a"], "result": APPROVAL_PASS},
        )

        assert r.json()["skipped"] == [{"user_id": "s_ap14a", "reason": "NOT_ENROLLED"}]
        assert await _approval_of(db, course_id, "s_ap14a") is None


class TestBatchApprove:
    """批次核可（AC 4 / `FR-ET-US16-05`）。"""

    async def test_批次核可跳過未完課者並逐筆回理由(self, client, db) -> None:
        teacher = await _user(db, "t_ap20")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        done_a = await _completed_student(db, course_id, "s_ap20a", item_id)
        done_b = await _completed_student(db, course_id, "s_ap20b", item_id)
        await _user(db, "s_ap20c", roles=(ROLE_STUDENT,))
        await _enroll(db, "s_ap20c", course_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [done_a, "s_ap20c", done_b], "result": APPROVAL_PASS},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] == 2
        assert body["skipped"] == [{"user_id": "s_ap20c", "reason": "NOT_COMPLETED"}]
        assert await _approval_of(db, course_id, done_a) is not None
        assert await _approval_of(db, course_id, done_b) is not None

    async def test_批次不通過不會無聲翻轉已通過者(self, client, db) -> None:
        """🔴 SA 裁示 Q2 = A。

        wireframe 的單列 UI 對已通過者**只給「撤銷」**（刻意不讓直接改判），但那一列的
        勾選框並未停用。照 spec 字面實作，「批次不通過」會把已通過翻成未通過，而
        `REVOKE_REASON` 是空的——因為那條路徑不經過撤銷，於是 `FR-ET-US16-06` 的
        「撤銷須填原因」被整個繞過，稽核上看到結果被改掉卻查不到理由。
        """
        teacher = await _user(db, "t_ap21")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        passed = await _completed_student(db, course_id, "s_ap21a", item_id)
        fresh = await _completed_student(db, course_id, "s_ap21b", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [passed], "result": APPROVAL_PASS},
        )

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [passed, fresh], "result": APPROVAL_FAIL},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] == 1
        assert body["skipped"] == [{"user_id": passed, "reason": "ALREADY_APPROVED"}]
        untouched = await _approval_of(db, course_id, passed)
        assert untouched is not None
        assert untouched.result == APPROVAL_PASS, "已通過者不可被批次翻成未通過"
        assert untouched.version == 1, "跳過就不該動版本號"

    async def test_同一批重複的user_id只寫一次(self, client, db) -> None:
        """去重在寫入之前——不去重的話第二次會走到 `ALREADY_APPROVED`，
        回應變成「核可 1 筆、跳過 1 筆」，而教師只選了一個人。
        """
        teacher = await _user(db, "t_ap22")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap22a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student, student], "result": APPROVAL_PASS},
        )

        assert r.json() == {"approved": 1, "skipped": []}
        count = await db.scalar(
            select(func.count(EtApproval.approval_id)).where(
                EtApproval.course_id == course_id, EtApproval.user_id == student
            )
        )
        assert count == 1


class TestRevokeAndReapprove:
    """撤銷與重核（AC 6 / 7 / `FR-ET-US16-06`）。"""

    async def _approved(self, client, db, teacher: str, course_id: int, student: str) -> int:
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None
        return row.version

    async def test_撤銷未填原因回422(self, client, db) -> None:
        teacher = await _user(db, "t_ap30")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap30a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)

        r = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "", "version": version},
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_005"

    async def test_撤銷原因僅空白亦回422(self, client, db) -> None:
        """🔴 Pydantic 的 `min_length=1` 會放行這個輸入。

        一個全是空白的原因等於沒有——而本表因唯一鍵而 update 覆寫，前次結果只存在
        `DP_AUDIT_LOG`，撤銷原因是唯一能回答「為什麼推翻」的欄位。
        """
        teacher = await _user(db, "t_ap31")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap31a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)

        r = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "   \t  ", "version": version},
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_005"

    async def test_撤銷寫入狀態原因與執行者(self, client, db) -> None:
        teacher = await _user(db, "t_ap32")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap32a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)

        r = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "考核紀錄登錄錯誤", "version": version},
        )

        assert r.status_code == 204, r.text
        row = await _approval_of(db, course_id, student)
        assert row is not None
        assert row.is_revoked is True
        assert row.revoke_reason == "考核紀錄登錄錯誤"
        assert row.revoked_by == teacher
        assert row.revoked_at is not None

    async def test_撤銷後綜合狀態回到待核可(self, client, db) -> None:
        teacher = await _user(db, "t_ap33")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap33a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)
        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "登錄錯誤", "version": version},
        )

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"][0]["approval_status"] == "PENDING"

    async def test_撤銷後重核以同一筆更新且清空撤銷欄位(self, client, db) -> None:
        """🔴 AC 7 的兩個要點：**列數仍為 1**，且 `REVOKE_*` 被清空。

        不清的話畫面會出現「已通過」卻帶著撤銷原因的列，而那筆撤銷早已被本次重核推翻。
        """
        teacher = await _user(db, "t_ap34")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap34a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)
        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "登錄錯誤", "version": version},
        )

        r = await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert r.json() == {"approved": 1, "skipped": []}, "已撤銷者不可被當成已核可而跳過"
        count = await db.scalar(
            select(func.count(EtApproval.approval_id)).where(
                EtApproval.course_id == course_id, EtApproval.user_id == student
            )
        )
        assert count == 1, "重核必須 update 同一筆，不可新建列"
        row = await _approval_of(db, course_id, student)
        assert row is not None
        assert row.is_revoked is False
        assert row.revoke_reason is None
        assert row.revoked_by is None
        assert row.revoked_at is None

    async def test_查無核可紀錄時撤銷回404(self, client, db) -> None:
        teacher = await _user(db, "t_ap35")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap35a", item_id)
        await db.commit()

        r = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "沒有這筆", "version": 1},
        )

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_003"

    async def test_版本不符回409(self, client, db) -> None:
        """AC 9 / `ET-MSG-ET03-308`：畫面過期了，請重新整理。"""
        teacher = await _user(db, "t_ap36")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap36a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)

        r = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "版本過期", "version": version + 99},
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_004"

    async def test_同一版本號不可撤銷兩次(self, client, db) -> None:
        """🔴 條件式 `UPDATE` 的 `IS_REVOKED = false` 那半段不只是樂觀鎖的補強。

        少了它，兩次帶同一個版本號的撤銷中第二次會**覆寫第一位教師填的原因與署名**，
        而兩次的 `VERSION` 在他們各自看到的畫面上都是對的。
        """
        teacher = await _user(db, "t_ap37")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap37a", item_id)
        await db.commit()
        version = await self._approved(client, db, teacher, course_id, student)
        first = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "第一位教師的原因", "version": version},
        )
        assert first.status_code == 204

        second = await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "第二位教師的原因", "version": version},
        )

        assert second.status_code == 409
        row = await _approval_of(db, course_id, student)
        assert row is not None
        assert row.revoke_reason == "第一位教師的原因"


class TestNotification:
    """核可通知信（AC 5 / `FR-ET-US16-08`）。"""

    async def test_核可通過寄APPROVAL_PASSED(self, client, db) -> None:
        teacher = await _user(db, "t_ap40", name="王主任")
        course_id = await _course(db, owner=teacher, name="血品安全")
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap40a", item_id, name="陳小明")
        await db.commit()

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        mails = await _pending_mails(db)
        assert len(mails) == 1, "params key 對不上時平台會寫 FAILED 的空信且不拋錯"
        assert mails[0].recipient == f"{student}@edms.local"
        assert "血品安全" in mails[0].subject
        assert "陳小明" in mails[0].body
        assert "王主任" in mails[0].body

    async def test_不通過不寄信(self, client, db) -> None:
        teacher = await _user(db, "t_ap41")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap41a", item_id)
        await db.commit()

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_FAIL},
        )

        assert await _pending_mails(db) == []

    async def test_撤銷不寄信(self, client, db) -> None:
        """撤銷需要教師當面說明，不該由系統自動發一封「你的核可被撤銷了」。"""
        teacher = await _user(db, "t_ap42")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap42a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None
        before = len(await _pending_mails(db))

        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "登錄錯誤", "version": row.version},
        )

        assert len(await _pending_mails(db)) == before

    async def test_撤銷後重核為通過會再寄一次信(self, client, db) -> None:
        """AC 7 的最後一句：「重核為 PASS 時**再寄信**」。

        重核走的是 `reapprove` 而非 `insert_approval`，兩條路徑在 `_write_approval` 裡
        都回 True、之後才判斷要不要寄——少了這條測試，日後若有人把寄信搬進
        `insert_approval` 那一側（看起來像「只有新建才通知」），重核就會靜默不寄，而學員
        不知道自己已經恢復通過。
        """
        teacher = await _user(db, "t_ap44")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap44a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None
        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "登錄錯誤", "version": row.version},
        )
        assert len(await _pending_mails(db)) == 1, "撤銷不寄信，此時仍只有首次核可那一封"

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        assert len(await _pending_mails(db)) == 2, "重核為通過必須再寄一次"

    async def test_撤銷後重核為不通過不寄信(self, client, db) -> None:
        """重核的寄信規則沿用 `FR-ET-US16-08`，不因為是「重核」而例外。"""
        teacher = await _user(db, "t_ap45")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap45a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None
        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "登錄錯誤", "version": row.version},
        )

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_FAIL},
        )

        assert len(await _pending_mails(db)) == 1, "重核為不通過不寄信"

    async def test_批次逐人一封不合批(self, client, db) -> None:
        """🔴 範本內文含 `{USER_NAME}`，而平台 `send_email` 對整批收件人**只渲染一次**。

        合批會讓三個人收到同一個名字的信——而且每一封都是「成功」，沒有任何訊號。
        """
        teacher = await _user(db, "t_ap43")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        names = {"s_ap43a": "甲學員", "s_ap43b": "乙學員", "s_ap43c": "丙學員"}
        for uid, name in names.items():
            await _completed_student(db, course_id, uid, item_id, name=name)
        await db.commit()

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": list(names), "result": APPROVAL_PASS},
        )

        mails = await _pending_mails(db)
        assert len(mails) == 3
        by_recipient = {m.recipient: m.body for m in mails}
        for uid, name in names.items():
            assert name in by_recipient[f"{uid}@edms.local"], "每個人的信必須帶自己的名字"


class TestIsolationFromCompletion:
    """核可獨立於完課（AC 10 / 11 / `FR-ET-US16-09`）。"""

    async def test_核可不改變完課統計(self, client, db) -> None:
        """核可前後的完課狀態、進度百分比、平均成績必須一模一樣。"""
        teacher = await _user(db, "t_ap50")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap50a", item_id)
        await db.commit()
        before = (await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))).json()["data"][0]

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        after = (await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))).json()["data"][0]
        for field in ("completion_status", "progress_pct", "avg_score"):
            assert before[field] == after[field], f"{field} 不該因核可而改變"

    async def test_核可不寫ET_ENROLLMENT的完課欄位(self, client, db) -> None:
        """那兩個欄位是死的——核可若「順手」推進它們，會讓 ET-14 的反向斷言測試變紅，
        也讓 ET04 / ET03 的即時計算與 DB 值開始不一致。
        """
        teacher = await _user(db, "t_ap51")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap51a", item_id)
        await db.commit()

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.course_id == course_id, EtEnrollment.user_id == student)
        )
        assert row is not None
        assert row.completion_status == COMPLETION_NOT_STARTED
        assert row.completed_at is None

    async def test_完課回退後核可紀錄仍在(self, client, db) -> None:
        """AC 11 / 場景 15：教師新增章節致完課回退為「進行中」，核可 MUST NOT 失效。

        綜合狀態此時顯示「未達核可資格」（完課條件不成立，核可 / 撤銷按鈕都不該出現），
        但 `ET_APPROVAL` 那一列**原封不動**——補完新項目後會自動回到「已通過」。
        """
        teacher = await _user(db, "t_ap52")
        course_id = await _course(db, owner=teacher)
        item_a = await _item(db, course_id, title="教材 A", order=1)
        student = await _completed_student(db, course_id, "s_ap52a", item_a)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        item_b = await _item(db, course_id, title="教材 B", order=2)  # 新增章節 → 完課回退
        await db.commit()

        listed = (await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))).json()["data"][0]
        assert listed["completion_status"] == "IN_PROGRESS"
        assert listed["approval_status"] == "NOT_ELIGIBLE"
        row = await _approval_of(db, course_id, student)
        assert row is not None and row.result == APPROVAL_PASS and row.is_revoked is False

        await _complete(db, student, course_id, item_b)  # 補完新項目
        await db.commit()
        again = (await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))).json()["data"][0]
        assert again["approval_status"] == "PASSED", "補完後應自動回到已通過，不需重新核可"


class TestApprovalInStudentList:
    """核可狀態併入 ET03 學員清單（AC 1 / `FR-ET-US16-02`）。"""

    async def test_未啟用核可時清單不帶核可狀態(self, client, db) -> None:
        teacher = await _user(db, "t_ap60")
        course_id = await _course(db, owner=teacher, require_approval=False)
        item_id = await _item(db, course_id, title="教材")
        await _completed_student(db, course_id, "s_ap60a", item_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"][0]["approval_status"] is None

    async def test_已啟用核可時完課者顯示待核可(self, client, db) -> None:
        teacher = await _user(db, "t_ap61")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        await _completed_student(db, course_id, "s_ap61a", item_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"][0]["approval_status"] == "PENDING"

    async def test_未完課者顯示未達核可資格(self, client, db) -> None:
        teacher = await _user(db, "t_ap62")
        course_id = await _course(db, owner=teacher)
        await _item(db, course_id, title="教材")
        await _user(db, "s_ap62a", roles=(ROLE_STUDENT,))
        await _enroll(db, "s_ap62a", course_id)
        await db.commit()

        r = await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))

        assert r.json()["data"][0]["approval_status"] == "NOT_ELIGIBLE"

    async def test_核可後清單帶核可人與時間(self, client, db) -> None:
        """wireframe 的「{核可人} 核可 {日期}」小字需要這兩個欄位。"""
        teacher = await _user(db, "t_ap63", name="王主任")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap63a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_FAIL, "result_note": "口試未通過"},
        )

        row = (await client.get(f"{_URL}/{course_id}/students", headers=_bearer(teacher))).json()["data"][0]

        assert row["approval_status"] == "FAILED"
        assert row["approved_by_name"] == "王主任"
        assert row["approved_at"] is not None
        assert row["approval_note"] == "口試未通過"
        assert row["approval_version"] == 1


class TestAudit:
    """稽核（`data-model` §ET_APPROVAL：歷程的唯一載體）。"""

    async def _logs(self, db) -> list[DpAuditLog]:
        rows = await db.scalars(select(DpAuditLog).where(DpAuditLog.func_name == "ET-APPROVAL"))
        return list(rows.all())

    async def test_核可寫稽核(self, client, db) -> None:
        teacher = await _user(db, "t_ap70")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap70a", item_id)
        await db.commit()

        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )

        logs = await self._logs(db)
        assert len(logs) == 1
        assert logs[0].action_type == "CREATE"
        assert logs[0].target_id == f"{course_id}:{student}"
        assert logs[0].created_user == teacher, "log_action 把 operator_id 寫進 CREATED_USER"

    async def test_撤銷後重核的稽核帶得回被覆寫的前次結果(self, client, db) -> None:
        """🔴 這是本表**唯一**能回答「上一次是什麼結果」的地方。

        `ET_APPROVAL` 因 `(COURSE_ID, USER_ID)` 唯一而 update 覆寫——重核之後，那筆
        「曾經被撤銷、原因是 X」在本表已經不存在了。`before_value` 漏寫的表現是本表
        看起來一切正常，而歷程永久消失。
        """
        teacher = await _user(db, "t_ap71")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap71a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None
        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "考核紀錄登錄錯誤", "version": row.version},
        )
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_FAIL, "result_note": "重考仍未通過"},
        )

        logs = sorted(await self._logs(db), key=lambda x: x.log_id)
        assert [x.action_type for x in logs] == ["CREATE", "UPDATE", "UPDATE"]
        assert "考核紀錄登錄錯誤" in (logs[2].before_value or ""), "重核必須留下被它覆寫的撤銷紀錄"

        # 🔴 撤銷那一列的 before 必須是**撤銷前**的狀態（未撤銷的 PASS）。
        #
        # 這條斷言存在的理由：ORM-enabled `update()` 會把 session 內符合條件的實體
        # **屬性同步成新值**。若 `before` 在 UPDATE 之後才序列化，它會變成撤銷**後**的
        # 樣子——而稽核照常寫出一列、欄位齊全、格式正確，只是 before 等於 after、
        # 內容失去意義。**不會有任何東西變紅**，除非像這裡一樣直接比對內容。
        #
        # （本 issue 的第一版正是這個形狀，但因為漏了 `model_validate` 而拋
        # `AttributeError` 炸得很大聲。把轉型寫在 UPDATE 之後就會安靜地錯。）
        assert '"is_revoked": false' in (logs[1].before_value or ""), "撤銷的 before 應為撤銷前狀態"
        assert '"is_revoked": true' in (logs[1].after_value or "")
        assert logs[1].before_value != logs[1].after_value

    async def test_撤銷原因不寫進稽核description(self, client, db) -> None:
        """原因是自由文字，寫進 `description` 就把 log injection 的面打開了。

        內容本身存在 `ET_APPROVAL.REVOKE_REASON`，由 `target_id` 對得回來。
        """
        teacher = await _user(db, "t_ap72")
        course_id = await _course(db, owner=teacher)
        item_id = await _item(db, course_id, title="教材")
        student = await _completed_student(db, course_id, "s_ap72a", item_id)
        await db.commit()
        await client.post(
            f"{_URL}/{course_id}/approvals",
            headers=_bearer(teacher),
            json={"user_ids": [student], "result": APPROVAL_PASS},
        )
        row = await _approval_of(db, course_id, student)
        assert row is not None

        await client.post(
            f"{_URL}/{course_id}/approvals/{student}/revoke",
            headers=_bearer(teacher),
            json={"reason": "注入測試\n偽造的稽核列", "version": row.version},
        )

        logs = sorted(await self._logs(db), key=lambda x: x.log_id)
        assert "偽造的稽核列" not in (logs[-1].description or "")
