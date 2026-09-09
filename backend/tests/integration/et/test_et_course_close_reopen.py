"""ET02 課程關閉與再開課整合測試（US11 / #288）。

狀態前提（`ensure_closable` / `ensure_reopenable` / `ensure_reopen_schedule`）與開放期間
判定（`is_within_open_window`）已在 `tests/unit/et/test_course_rules.py` 以純函式涵蓋。
此處只驗**需要真 DB 才驗得了**的事：

1. 兩支端點的接線與各欄位的實際寫入（`CLOSED_AT` 寫了、`URGENT_REMIND_SENT` 歸零）
2. 三個刻意**不動**的欄位（`CLOSED_AT` 於再開課保留、`FIRST_PUBLISHED_AT`、`INVITATION_CODE`）
3. 樂觀鎖（版本不符回 409）
4. 擁有權邊界
5. **再開課重跑發布六項檢核**（SA Q2 裁示 A）——需要真的把課程弄壞才驗得出
6. 關閉 / 再開課可重複多次
7. 關閉期間教師端仍可編輯課程內容（AC 6）

關閉後**學員端**的行為在 `test_et_closed_course_behaviours.py`（那些跨七個子模組，
不屬於本檔的「兩支端點」範圍）。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ROLE_TEACHER,
)
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str) -> str:
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
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


async def _tag(db, name: str) -> int:
    """標籤不存在才建——「全體」等為 bootstrap 種子，無條件 INSERT 會撞 `UQ_ET_TAG_NAME`。"""
    now = utcnow()
    tag_id = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
    if tag_id is None:
        tag = EtTag(tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=now, deleted=0)
        db.add(tag)
        await db.flush()
        tag_id = tag.tag_id
    return tag_id


async def _published_course(client, db, uid: str) -> dict:
    """一門**已發布且恰好滿足全部檢核**的課程（1 章節 + 1 教材 + 1 標籤 + 起訖時間）。

    ⚠️ 標籤刻意**不用「全體」**：那個內建標籤會在發布時觸發標籤自動邀請，把全站學員
    角色者都加進課程並排入通知信（#273 的既有行為）。本檔驗的是狀態轉換，不需要那些
    副作用，也不該讓測試相依於 DB 裡有多少學員。
    """
    created = await client.post(
        _COURSES,
        json={
            "course_name": "關閉測試課程",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2027-09-30T00:00:00Z",
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]

    tag_id = await _tag(db, f"標籤{cid}")
    db.add(EtCourseTag(course_id=cid, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]
    item = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(uid),
    )
    assert item.status_code == 201, item.text

    published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
    assert published.status_code == 200, published.text
    return {
        "course_id": cid,
        "chapter_id": chapter_id,
        "item_id": item.json()["item_id"],
        "version": published.json()["version"],
        "invitation_code": published.json()["invitation_code"],
    }


async def _course_row(db, course_id: int) -> EtCourse:
    db.expire_all()
    row = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
    assert row is not None
    return row


def _future(days: int) -> str:
    from datetime import timedelta

    return (utcnow() + timedelta(days=days)).replace(microsecond=0).isoformat()


class TestClose:
    async def test_關閉立即轉CLOSED並寫入關閉時間(self, client, db) -> None:
        """AC 1 / FR-ET-US11-02：立即轉換、不延遲、無過渡狀態。"""
        uid = await _user(db, "t_cl01")
        ctx = await _published_course(client, db, uid)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == COURSE_CLOSED
        assert r.json()["closed_at"] is not None
        row = await _course_row(db, ctx["course_id"])
        assert row.status == COURSE_CLOSED
        assert row.closed_at is not None
        assert row.version == ctx["version"] + 1

    async def test_關閉不動起訖時間與邀請碼(self, client, db) -> None:
        """手動關閉時閱課期間可能還沒到——把 `OPEN_END_AT` 改成 now 會讓「為什麼關的」消失。

        邀請碼亦不動：關閉期間失效但**不作廢**（再開課沿用原碼）。
        """
        uid = await _user(db, "t_cl02")
        ctx = await _published_course(client, db, uid)
        before = await _course_row(db, ctx["course_id"])
        end_before, code_before, first_pub_before = (
            before.open_end_at,
            before.invitation_code,
            before.first_published_at,
        )

        await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        row = await _course_row(db, ctx["course_id"])
        assert row.open_end_at == end_before
        assert row.invitation_code == code_before
        assert row.first_published_at == first_pub_before

    async def test_草稿課程關閉回409(self, client, db) -> None:
        """AC 2：草稿沒有學員也沒有邀請碼，關閉它沒有語意（要移除走 DELETE）。"""
        uid = await _user(db, "t_cl03")
        created = await client.post(_COURSES, json={"course_name": "草稿"}, headers=_bearer(uid))
        cid = created.json()["course_id"]

        r = await client.post(f"{_COURSES}/{cid}/close", json={"version": 0}, headers=_bearer(uid))

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_COURSE_006"

    async def test_已關閉課程再關閉回409(self, client, db) -> None:
        """否則會再寫一次 `CLOSED_AT`，把最近一次關閉時間覆蓋成第二次點擊的時間。"""
        uid = await _user(db, "t_cl04")
        ctx = await _published_course(client, db, uid)
        first = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        assert first.status_code == 200

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": first.json()["version"]}, headers=_bearer(uid)
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_COURSE_006"

    async def test_版本不符回409(self, client, db) -> None:
        """兩個分頁各關一次時的第二次——樂觀鎖攔在 UPDATE 的 WHERE 上。"""
        uid = await _user(db, "t_cl05")
        ctx = await _published_course(client, db, uid)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"] + 99}, headers=_bearer(uid)
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_非擁有者關閉回403(self, client, db) -> None:
        """AC 11。走的是 `course/rules.ensure_owner`，與編輯 / 刪除同一個閘。"""
        owner = await _user(db, "t_cl06")
        other = await _user(db, "t_cl06b")
        ctx = await _published_course(client, db, owner)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(other)
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"
        assert (await _course_row(db, ctx["course_id"])).status == COURSE_PUBLISHED

    async def test_關閉寫入稽核紀錄(self, client, db) -> None:
        """`spec.md` §稽核來源功能碼明列 `ET-COURSE` 涵蓋「關閉 / 再開課」，US11 在表內。

        ⚠️ 這與 #284（US13 不在表內故不寫稽核）**方向相反**，不要把那次的結論套過來。
        """
        from app.dp.audit.models import DpAuditLog

        uid = await _user(db, "t_cl07")
        ctx = await _published_course(client, db, uid)

        await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        rows = (
            await db.scalars(
                select(DpAuditLog).where(
                    DpAuditLog.func_name == "ET-COURSE", DpAuditLog.target_id == str(ctx["course_id"])
                )
            )
        ).all()
        assert any(r.description == "關閉課程" for r in rows)


class TestReopen:
    async def test_再開課回PUBLISHED並歸零加急提醒旗標(self, client, db) -> None:
        """AC 8 / FR-ET-US11-09。

        `URGENT_REMIND_SENT` 必須歸零——否則依新起訖時間算出的訖止前 3 天加急提醒不會
        再發（`ET-16` 以該旗標判斷是否已寄）。
        """
        uid = await _user(db, "t_ro01")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        # 模擬上一輪已寄過加急提醒
        row = await _course_row(db, ctx["course_id"])
        row.urgent_remind_sent = True
        await db.flush()

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "關閉測試課程",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == COURSE_PUBLISHED
        row = await _course_row(db, ctx["course_id"])
        assert row.status == COURSE_PUBLISHED
        assert row.urgent_remind_sent is False

    async def test_再開課不清空關閉時間(self, client, db) -> None:
        """FR-ET-US11-10：`CLOSED_AT` 記錄最近一次關閉時間，再開課後**保留供追溯**。

        故前端不可用「有沒有值」判斷是否已關閉——那要看 `status`。
        """
        uid = await _user(db, "t_ro02")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        closed_at_before = (await _course_row(db, ctx["course_id"])).closed_at

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None
        assert (await _course_row(db, ctx["course_id"])).closed_at == closed_at_before

    async def test_再開課沿用原邀請碼且不動首次發布時間(self, client, db) -> None:
        """Clarifications：再開課不重發邀請、不重產邀請碼（沿用原 8 碼，僅恢復有效）。

        `FIRST_PUBLISHED_AT` 歷經再開課不變（`data-model` §ET_COURSE）——`mark_published`
        的 `COALESCE` 已為此預留，此處確認再開課真的沒有覆寫它。
        """
        uid = await _user(db, "t_ro03")
        ctx = await _published_course(client, db, uid)
        before = await _course_row(db, ctx["course_id"])
        code_before, first_pub_before = before.invitation_code, before.first_published_at
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        row = await _course_row(db, ctx["course_id"])
        assert row.invitation_code == code_before
        assert row.first_published_at == first_pub_before

    async def test_已發布課程再開課回409(self, client, db) -> None:
        """與 `ET_COURSE_006` 分碼：兩者下一步不同（去發布 / 去再開課）。"""
        uid = await _user(db, "t_ro04")
        ctx = await _published_course(client, db, uid)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": ctx["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_COURSE_007"

    async def test_再開課缺起訖時間回422(self, client, db) -> None:
        """AC 8：**強制**帶新起訖時間，未填妥不可送出（schema 層必填 → `COMMON_422`）。"""
        uid = await _user(db, "t_ro05")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={"course_name": "x", "version": closed.json()["version"]},
            headers=_bearer(uid),
        )

        assert r.status_code == 422
        assert (await _course_row(db, ctx["course_id"])).status == COURSE_CLOSED

    async def test_再開課之訖止時間已過回_ET_COURSE_008(self, client, db) -> None:
        """🔴 SA Q3 裁示 A 的唯一驗證點（HTTP 層真的回得出這個碼）。

        不檢核的話直呼 API 就能造出「已發布但期間已過」的課程：教師端看到已發布、
        學員端卻被 `is_within_open_window` 判為視同關閉而進不去，狀態自相矛盾。

        ⚠️ 也確認這個碼**沒有被 schema 層先攔掉**（#284 的 `ET_SURVEY_016` 曾經如此）
        ——起訖仍滿足「迄 > 起」，只是兩者都在過去。
        """
        uid = await _user(db, "t_ro06")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": "2020-01-01T00:00:00Z",
                "open_end_at": "2020-12-31T00:00:00Z",
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_COURSE_008"
        assert r.json()["error_message"] == "請重新設定一組新的起訖時間後方可再開課"
        assert (await _course_row(db, ctx["course_id"])).status == COURSE_CLOSED

    async def test_再開課之起始時間可落在過去(self, client, db) -> None:
        """裁示 A 只檢核訖止——「補開一段已經開始的期間」是合理操作。"""
        uid = await _user(db, "t_ro07")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": "2020-01-01T00:00:00Z",
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text

    async def test_非擁有者再開課回403(self, client, db) -> None:
        uid = await _user(db, "t_ro08")
        other = await _user(db, "t_ro08b")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(other),
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestReopenRerunsPublishChecks:
    """🔴 SA Q2 裁示 A：再開課重跑發布六項檢核。

    這組測試需要「真的把課程弄壞」才驗得出來——關閉期間教師端可編輯（AC 6），所以
    「刪光章節再開課」是使用者做得到的操作。不重跑檢核等於把發布檢核變成一次性的。
    """

    async def test_關閉期間刪光章節後再開課被擋(self, client, db) -> None:
        uid = await _user(db, "t_rc01")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        # 關閉期間可編輯（AC 6）——刪掉唯一的章節，課程因此不再滿足「至少 1 章節 + 1 教材」
        deleted = await client.delete(f"/api/et/chapters/{ctx['chapter_id']}", headers=_bearer(uid))
        assert deleted.status_code == 204, deleted.text

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_PUBLISH_001"
        codes = {b["code"] for b in r.json()["blockers"]}
        assert "NO_CHAPTER" in codes
        assert (await _course_row(db, ctx["course_id"])).status == COURSE_CLOSED, "被擋下時不得改變狀態"

    async def test_檢核通過則正常再開課(self, client, db) -> None:
        """對照組：沒弄壞任何東西時，重跑檢核不會誤擋。"""
        uid = await _user(db, "t_rc02")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text

    async def test_再開課不重複帶入標籤學員也不重寄信(self, client, db) -> None:
        """再開課不是一次新的招生——`publish` 的標籤帶入與寄信刻意不呼叫。

        以「沒有新增 `DP_EMAIL_LOG` 列」表達：課程掛的是專屬標籤（無人掛），故發布當下
        本來就沒有帶入任何人；若再開課誤呼叫 `send_course_invite`，那支對空清單亦不寄，
        故改以**選課列數不變**與**信件列數不變**兩者一起驗。
        """
        from app.dp.notify.models import DpEmailLog
        from app.et.progress.models import EtEnrollment

        uid = await _user(db, "t_rc03")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        enroll_before = len(
            (await db.scalars(select(EtEnrollment).where(EtEnrollment.course_id == ctx["course_id"]))).all()
        )
        mail_before = len((await db.scalars(select(DpEmailLog))).all())

        await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        enroll_after = len(
            (await db.scalars(select(EtEnrollment).where(EtEnrollment.course_id == ctx["course_id"]))).all()
        )
        assert enroll_after == enroll_before
        assert len((await db.scalars(select(DpEmailLog))).all()) == mail_before


class TestRepeatable:
    async def test_關閉再開課可重複兩輪(self, client, db) -> None:
        """AC 10 / FR-ET-US11-10。兩支端點各只認一種來源狀態，可重複是天然成立的。"""
        uid = await _user(db, "t_rp01")
        ctx = await _published_course(client, db, uid)
        version = ctx["version"]

        for _round in range(2):
            closed = await client.post(
                f"{_COURSES}/{ctx['course_id']}/close", json={"version": version}, headers=_bearer(uid)
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["status"] == COURSE_CLOSED
            reopened = await client.post(
                f"{_COURSES}/{ctx['course_id']}/reopen",
                json={
                    "course_name": "x",
                    "open_start_at": _future(1),
                    "open_end_at": _future(400),
                    "version": closed.json()["version"],
                },
                headers=_bearer(uid),
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["status"] == COURSE_PUBLISHED
            version = reopened.json()["version"]

        row = await _course_row(db, ctx["course_id"])
        assert row.status == COURSE_PUBLISHED
        assert row.version == ctx["version"] + 4, "兩輪各兩次寫入，版本共 +4"


class TestEditableWhileClosed:
    async def test_關閉期間仍可編輯課程內容(self, client, db) -> None:
        """AC 6 / FR-ET-US11-07（2026-07-02 變更：原「唯讀」改為可編輯，供準備下次開課）。

        驗兩件事：改基本資料、新增章節。兩者都是 `PUT /courses/{id}` 與
        `POST /courses/{id}/chapters`——**它們本來就沒有檢核狀態**，故本測試是釘住
        「不要在日後為關閉加上唯讀限制」，而非驗證新寫的程式碼。
        """
        uid = await _user(db, "t_ed01")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        tag_id = await _tag(db, f"標籤{ctx['course_id']}")

        updated = await client.put(
            f"{_COURSES}/{ctx['course_id']}",
            json={
                "course_name": "關閉期間改過的名稱",
                "tag_ids": [tag_id],
                "require_approval": False,
                "open_start_at": "2026-09-01T00:00:00Z",
                "open_end_at": "2027-09-30T00:00:00Z",
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )
        assert updated.status_code == 204, updated.text

        added = await client.post(
            f"{_COURSES}/{ctx['course_id']}/chapters", json={"chapter_name": "關閉期間新增的章節"}, headers=_bearer(uid)
        )
        assert added.status_code == 201, added.text

        row = await _course_row(db, ctx["course_id"])
        assert row.course_name == "關閉期間改過的名稱"
        assert row.status == COURSE_CLOSED, "編輯內容不應改變課程狀態"


class TestReturnedVersionMatchesDb:
    """三支狀態轉換端點回的 `version` 必須等於 DB 實際值。

    #288 開發時發現 `publish` 回的是 `course.version + 1` 而 DB 已經是該值——因為
    `update(EtCourse)` 是 ORM-enabled UPDATE，SQLAlchemy 會同步 identity map，執行後
    手上物件的 `version` 已是新值，再 `+ 1` 就多加一次。

    那個偏差沒有造成使用者可見的問題（前端只顯示回應裡的邀請碼，寫入用的是
    `GET /courses/{id}` 重抓的版本），但它讓本檔的測試 helper 必須把「publish 回的版本
    不能信」寫進程式碼。三支端點一起改用 `RETURNING`，並以本組測試釘住。
    """

    async def test_publish_回的版本等於DB(self, client, db) -> None:
        uid = await _user(db, "t_vr01")
        ctx = await _published_course(client, db, uid)
        assert (await _course_row(db, ctx["course_id"])).version == ctx["version"]

    async def test_close_回的版本等於DB(self, client, db) -> None:
        uid = await _user(db, "t_vr02")
        ctx = await _published_course(client, db, uid)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        assert (await _course_row(db, ctx["course_id"])).version == r.json()["version"]

    async def test_reopen_回的版本等於DB(self, client, db) -> None:
        uid = await _user(db, "t_vr03")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert (await _course_row(db, ctx["course_id"])).version == r.json()["version"]

    async def test_回的版本可直接用於下一次寫入(self, client, db) -> None:
        """最實際的一條：拿端點回的版本立刻做下一個操作，不該 409。

        這正是 off-by-one 會咬到的地方——前端若信任回應的版本就會撞樂觀鎖。
        """
        uid = await _user(db, "t_vr04")
        ctx = await _published_course(client, db, uid)

        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        reopened = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )
        again = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": reopened.json()["version"]}, headers=_bearer(uid)
        )

        assert closed.status_code == 200, closed.text
        assert reopened.status_code == 200, reopened.text
        assert again.status_code == 200, again.text
