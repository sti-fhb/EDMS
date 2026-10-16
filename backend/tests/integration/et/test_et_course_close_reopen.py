"""ET05 課程關閉與再開課整合測試（US11 / #288）。

狀態前提（`ensure_closable` / `ensure_reopenable` / `ensure_reopen_schedule`）與「視同關閉」
判定（`is_effectively_closed`）已在 `tests/unit/et/test_course_rules.py` 以純函式涵蓋。
此處只驗**需要真 DB 才驗得了**的事：

1. 兩支端點的接線與各欄位的實際寫入（`CLOSED_AT` 寫了、`URGENT_REMIND_SENT` 歸零）
2. 三個刻意**不動**的欄位（`CLOSED_AT` 於再開課保留、`FIRST_PUBLISHED_AT`、`INVITATION_CODE`）
3. 樂觀鎖（版本不符回 409）
4. 擁有權邊界**與角色閘**（兩道不同的閘：`ensure_owner` 擋不住「沒有教師角色的擁有者」）
5. **再開課重跑發布六項檢核**（SA Q2 裁示 A）——需要真的把課程弄壞才驗得出
6. 關閉 / 再開課可重複多次
7. 關閉期間教師端仍可編輯課程內容（AC 6）
8. **再開課請求以前端實際送出的欄位為準**（`test_以前端實際送出的欄位再開課`）——
   其餘案例為了方便多塞了 `course_name`，那掩蓋過一次真實環境必然失敗的缺陷

關閉後**學員端**的行為在 `test_et_closed_course_behaviours.py`（那些跨七個子模組，
不屬於本檔的「兩支端點」範圍）。
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
)
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole
from tests.integration.et._tag_pairs import all_units_id, role_pair

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *, role: str = ROLE_TEACHER) -> str:
    """建使用者並賦予單一 ET 角色（預設教師——本檔多數案例是教師操作）。

    `role` 可覆寫，用於驗**角色閘**（與擁有權是兩道不同的閘，見
    `test_學員角色關閉回403`）。
    """
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
    db.add(EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0))
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
    db.add(
        EtCourseTag(
            unit_tag_id=await all_units_id(db),
            course_id=cid,
            tag_id=tag_id,
            created_user="SYSTEM",
            created_date=utcnow(),
            deleted=0,
        )
    )
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

    async def test_學員角色關閉回403(self, client, db) -> None:
        """角色閘（`require_et_roles(ET_TEACHER, ET_ADMIN)`）——與擁有權是**兩道不同的閘**。

        原本全部測試都用教師帳號，所以 `dependencies=[...]` 那一行漏掉時不會有任何測試
        變紅：擁有權閘擋得住「別人的課」，但擋不住「這個人根本沒有教師角色」。
        """
        owner = await _user(db, "t_cl08")
        ctx = await _published_course(client, db, owner)
        student = await _user(db, "s_cl08", role=ROLE_STUDENT)

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(student)
        )

        assert r.status_code == 403, r.text
        assert (await _course_row(db, ctx["course_id"])).status == COURSE_PUBLISHED

    async def test_教師角色被停用後即使仍是擁有者也擋下(self, client, db) -> None:
        """被撤掉 `ET_TEACHER` 但仍是 `OWNER_ID` 的人——`ensure_owner` 對他是**通過的**，
        唯一擋他的就是角色閘。這是最容易被漏掉的一種情境。
        """
        owner = await _user(db, "t_cl09")
        ctx = await _published_course(client, db, owner)
        await db.execute(update(EtUserRole).where(EtUserRole.user_id == owner).values(is_active=False))
        await db.flush()

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(owner)
        )

        assert r.status_code == 403, r.text
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
    async def test_以前端實際送出的欄位再開課(self, client, db) -> None:
        """🔴 迴歸測試：請求**只帶起訖時間與 version**，不帶 `course_name`。

        `ReopenCourseReq` 原本繼承 `_CourseFields`（為了沿用時區補正與「迄 > 起」兩個
        驗證器），於是把 `course_name` 的**必填性**一起繼承了。前端的 `ReopenPayload`
        只有三個欄位，所以真實操作每一次都被擋成 422 `COMMON_422`「以下欄位不符規定：
        course_name」——而教師在再開課視窗從未見過那個欄位，AC 8 在真實環境完全不可用。

        本檔其餘案例都沒抓到，是因為它們在 JSON 裡**多塞了** `course_name`（那不是真實
        呼叫端會送的內容）；前端測試的 MSW handler 又不驗 request body。三層測試各自
        成立，卻沒有一層驗過「前端實際組出的 payload 能通過後端 schema」。

        ⚠️ 這條測試的 payload 必須與 `frontend/src/et/courses/schemas.ts` 的
        `ReopenPayload` **逐欄一致**。改動任一邊時請同步。
        """
        uid = await _user(db, "t_ro00")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == COURSE_PUBLISHED

    async def test_再開課不改動課程名稱(self, client, db) -> None:
        """再開課只改起訖與狀態。夾帶 `course_name` 也不會被寫入（schema 已無此欄位）。

        基本資料的修改走 `PUT /courses/{id}`——兩支端點的職責不重疊，否則「再開課」會
        變成一個可以順手改任何欄位的後門。
        """
        uid = await _user(db, "t_ro00b")
        ctx = await _published_course(client, db, uid)
        original = (await _course_row(db, ctx["course_id"])).course_name
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        r = await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={
                "course_name": "被夾帶的新名稱",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert (await _course_row(db, ctx["course_id"])).course_name == original

    async def test_再開課寫入稽核紀錄(self, client, db) -> None:
        """與 `test_關閉寫入稽核紀錄` 對稱——US11 在 `spec.md` §稽核來源功能碼表內。

        關閉有測試、再開課沒有的話，日後重構誤刪 `_log` 只會讓一半的路徑變紅。
        """
        from app.dp.audit.models import DpAuditLog

        uid = await _user(db, "t_ro08")
        ctx = await _published_course(client, db, uid)
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )

        await client.post(
            f"{_COURSES}/{ctx['course_id']}/reopen",
            json={"open_start_at": _future(1), "open_end_at": _future(400), "version": closed.json()["version"]},
            headers=_bearer(uid),
        )

        rows = (
            await db.scalars(
                select(DpAuditLog).where(
                    DpAuditLog.func_name == "ET-COURSE", DpAuditLog.target_id == str(ctx["course_id"])
                )
            )
        ).all()
        assert any(r.description == "再開課" for r in rows)

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
        """Clarifications：再開課不重產邀請碼（沿用原 8 碼，僅恢復有效）。

        > 原文含「不重發邀請」——#678 起再開課會依受訓對象對新符合者寄邀請信（見
        > `TestReopenAutoEnrollsAudiences`），本條只守邀請碼不變。

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

    async def test_關閉期間的零題問卷停用後可再開課(self, client, db) -> None:
        """#611：再開課的導引寫「新增至少 1 題，或**停用**該問卷」——照做之後不可再被同一條擋下。

        停用前先以 publish-check 確認這門課**確實**被 `SURVEY_NO_QUESTION` 擋著：少了這一步，
        後面的 200 也可能只是因為問卷根本沒建成功。錨點用 publish-check（回 200）而不是一次
        失敗的再開課——同一條測試裡的失敗請求會連帶回滾前置建立的使用者列。
        """
        uid = await _user(db, "t_rc04")
        ctx = await _published_course(client, db, uid)
        cid = ctx["course_id"]
        closed = await client.post(f"{_COURSES}/{cid}/close", json={"version": ctx["version"]}, headers=_bearer(uid))
        assert closed.status_code == 200, closed.text
        # 關閉中的課程不能刪問卷、只能停用（ET_SURVEY_007），正是本 issue 的情境
        survey = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "s"}, headers=_bearer(uid))
        assert survey.status_code == 201, survey.text

        before = await client.get(f"{_COURSES}/{cid}/publish-check", headers=_bearer(uid))
        assert [b["code"] for b in before.json()["blockers"]] == ["SURVEY_NO_QUESTION"]

        disabled = await client.put(
            f"/api/et/surveys/{survey.json()['survey_id']}",
            json={"survey_name": "s", "is_active": False, "version": survey.json()["version"]},
            headers=_bearer(uid),
        )
        assert disabled.status_code == 204, disabled.text

        r = await client.post(
            f"{_COURSES}/{cid}/reopen",
            json={
                "course_name": "x",
                "open_start_at": _future(1),
                "open_end_at": _future(400),
                "version": closed.json()["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text

    async def test_再開課無新符合者時不帶入也不寄信(self, client, db) -> None:
        """再開課會依受訓對象帶入新符合者（#678）；**沒有新符合者時**不得產生任何選課列或信件。

        課程掛的是專屬標籤（無人掛），故沒有任何人符合。以**選課列數不變**與**信件列數
        不變**兩者一起驗。有新符合者／既有學員／已移除者的情形見
        `TestReopenAutoEnrollsAudiences`。

        > 本條原名「再開課不重複帶入標籤學員也不重寄信」，斷言「標籤帶入刻意不呼叫」——
        > #678 推翻該設計，故改為只斷言空集合的情形。
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
                "audiences": [await role_pair(db, tag_id)],
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


class TestReopenAutoEnrollsAudiences:
    """再開課比照發布：依**目前全部**受訓對象配對帶入新符合者並寄邀請信（#678）。

    #586 起已關閉課程可增刪受訓對象，而關閉期間不帶入（FR-ET-US11-07）、貼標追溯也排除
    已關閉課程——若再開課也不帶入，關閉期間新增的配對**永遠不會被帶入**，畫面上卻顯示
    它已在課程裡。既有學員不重複加入、已移除者不帶回，靠 `bulk_enroll_returning` 的
    `ON CONFLICT DO NOTHING`（⛔ 勿改成 DO UPDATE）。
    """

    @staticmethod
    async def _pending_invites(db, recipient: str) -> list:
        from app.dp.notify.models import DpEmailLog

        # 篩 PENDING：範本參數對不上時信會以 FAILED 落庫，只數列數會假陽性
        return list(
            await db.scalars(
                select(DpEmailLog).where(
                    DpEmailLog.template_code == "COURSE_INVITE",
                    DpEmailLog.recipient == recipient,
                    DpEmailLog.status == "PENDING",
                )
            )
        )

    @staticmethod
    async def _enrollment(db, user_id: str, course_id: int):
        from app.et.progress.models import EtEnrollment

        db.expire_all()
        return await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == user_id, EtEnrollment.course_id == course_id)
        )

    @staticmethod
    async def _seed_enrollment(db, user_id: str, course_id: int, *, removed: bool) -> None:
        from app.et.constants import COMPLETION_NOT_STARTED, SOURCE_TAG_DEFAULT
        from app.et.progress.models import EtEnrollment

        db.add(
            EtEnrollment(
                user_id=user_id,
                course_id=course_id,
                join_source=SOURCE_TAG_DEFAULT,
                joined_at=utcnow(),
                completion_status=COMPLETION_NOT_STARTED,
                is_removed=removed,
                removed_at=utcnow() if removed else None,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()

    @staticmethod
    async def _close(client, uid: str, ctx: dict) -> int:
        closed = await client.post(
            f"{_COURSES}/{ctx['course_id']}/close", json={"version": ctx["version"]}, headers=_bearer(uid)
        )
        assert closed.status_code == 200, closed.text
        return closed.json()["version"]

    @staticmethod
    async def _reopen(client, uid: str, course_id: int, version: int, start: str) -> None:
        r = await client.post(
            f"{_COURSES}/{course_id}/reopen",
            json={"open_start_at": start, "open_end_at": _future(400), "version": version},
            headers=_bearer(uid),
        )
        assert r.status_code == 200, r.text

    async def test_關閉期間新增的受訓對象於再開課時帶入並寄信_信內為新起訖(self, client, db) -> None:
        from datetime import datetime

        from app.et.notify.course_invite import format_open_at
        from tests.integration.et._tag_pairs import new_tag, pair_course, pair_user

        uid = await _user(db, "t_ra01")
        ctx = await _published_course(client, db, uid)
        version = await self._close(client, uid, ctx)

        # 關閉期間新增一組受訓對象，且有一位相符的學員
        role = await new_tag(db, "職位_ra01")
        await pair_course(db, ctx["course_id"], role)
        student = await _user(db, "s_ra01", role=ROLE_STUDENT)
        await pair_user(db, student, role)
        assert await self._enrollment(db, student, ctx["course_id"]) is None

        start = _future(3)
        await self._reopen(client, uid, ctx["course_id"], version, start)

        enrolled = await self._enrollment(db, student, ctx["course_id"])
        assert enrolled is not None and enrolled.is_removed is False
        invites = await self._pending_invites(db, f"{student}@edms.local")
        assert len(invites) == 1
        # 信內須為**新**起訖（再開課剛改過）。⚠️ 這條驗的是結果，不是 `enroll_audiences` 的
        # `refresh`：ORM UPDATE 已同步 identity map，拿掉 refresh 這條照樣綠（見該方法 docstring）
        assert format_open_at(datetime.fromisoformat(start)) in invites[0].body
        # 不重產邀請碼：信中為關閉前那一組
        assert ctx["invitation_code"] in invites[0].body

    async def test_關閉期間被貼上既有配對標籤的學員也於再開課時帶入(self, client, db) -> None:
        """貼標追溯排除已關閉課程，故這種人在關閉期間同樣沒被帶入——須依**全部**配對帶入。"""
        from tests.integration.et._tag_pairs import pair_user

        uid = await _user(db, "t_ra02")
        ctx = await _published_course(client, db, uid)
        version = await self._close(client, uid, ctx)

        existing_role = await _tag(db, f"標籤{ctx['course_id']}")
        student = await _user(db, "s_ra02", role=ROLE_STUDENT)
        await pair_user(db, student, existing_role)

        await self._reopen(client, uid, ctx["course_id"], version, _future(1))

        assert await self._enrollment(db, student, ctx["course_id"]) is not None
        assert len(await self._pending_invites(db, f"{student}@edms.local")) == 1

    async def test_既有學員不重複加入也不收信(self, client, db) -> None:
        from app.et.progress.models import EtEnrollment
        from tests.integration.et._tag_pairs import pair_user

        uid = await _user(db, "t_ra03")
        ctx = await _published_course(client, db, uid)
        existing_role = await _tag(db, f"標籤{ctx['course_id']}")
        student = await _user(db, "s_ra03", role=ROLE_STUDENT)
        await pair_user(db, student, existing_role)
        await self._seed_enrollment(db, student, ctx["course_id"], removed=False)
        # 正向錨點：同配對下另一位新符合者確實被帶入——證明帶入真的跑過
        fresh = await _user(db, "s_ra03b", role=ROLE_STUDENT)
        await pair_user(db, fresh, existing_role)
        version = await self._close(client, uid, ctx)

        await self._reopen(client, uid, ctx["course_id"], version, _future(1))

        assert await self._enrollment(db, fresh, ctx["course_id"]) is not None
        rows = list(
            await db.scalars(
                select(EtEnrollment).where(EtEnrollment.user_id == student, EtEnrollment.course_id == ctx["course_id"])
            )
        )
        assert len(rows) == 1
        assert await self._pending_invites(db, f"{student}@edms.local") == []

    async def test_已移除的學員不被帶回也不收信(self, client, db) -> None:
        from tests.integration.et._tag_pairs import pair_user

        uid = await _user(db, "t_ra04")
        ctx = await _published_course(client, db, uid)
        existing_role = await _tag(db, f"標籤{ctx['course_id']}")
        removed = await _user(db, "s_ra04", role=ROLE_STUDENT)
        await pair_user(db, removed, existing_role)
        await self._seed_enrollment(db, removed, ctx["course_id"], removed=True)
        # 正向錨點：同配對下另一位新符合者確實被帶入——否則「沒被帶回」在帶入根本沒執行時也恆真
        fresh = await _user(db, "s_ra04b", role=ROLE_STUDENT)
        await pair_user(db, fresh, existing_role)
        version = await self._close(client, uid, ctx)

        await self._reopen(client, uid, ctx["course_id"], version, _future(1))

        assert await self._enrollment(db, fresh, ctx["course_id"]) is not None
        row = await self._enrollment(db, removed, ctx["course_id"])
        assert row is not None and row.is_removed is True
        assert await self._pending_invites(db, f"{removed}@edms.local") == []

    async def test_延長期間讓視同關閉的課程復活時比照再開課帶入(self, client, db) -> None:
        """`PUT` 延長期間讓「期間已過、狀態仍為 PUBLISHED」的課程復活——期間已過時加的配對同樣沒被帶入過。"""
        from datetime import timedelta

        from tests.integration.et._tag_pairs import audiences_req, new_tag, pair_course, pair_user

        uid = await _user(db, "t_ra05")
        ctx = await _published_course(client, db, uid)
        # 讓課程視同關閉：期間已過、狀態仍為 PUBLISHED
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_start_at=utcnow() - timedelta(days=30), open_end_at=utcnow() - timedelta(days=1))
        )
        role = await new_tag(db, "職位_ra05")
        await pair_course(db, ctx["course_id"], role)
        student = await _user(db, "s_ra05", role=ROLE_STUDENT)
        await pair_user(db, student, role)
        db.expire_all()

        detail = (await client.get(f"{_COURSES}/{ctx['course_id']}", headers=_bearer(uid))).json()
        r = await client.put(
            f"{_COURSES}/{ctx['course_id']}",
            json={
                "course_name": detail["course_name"],
                "open_start_at": detail["open_start_at"],
                "open_end_at": _future(200),
                "audiences": audiences_req(detail),
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 204, r.text
        assert await self._enrollment(db, student, ctx["course_id"]) is not None
        assert len(await self._pending_invites(db, f"{student}@edms.local")) == 1

    async def test_同一次PUT復活並新增配對_依全部配對帶入且各只寄一封(self, client, db) -> None:
        """復活與新增配對同時發生——走「全部配對」那支，舊配對的人也要帶入。

        ⚠️ 本條**驗不到**「`if revived` / `elif tags_add` 兩者擇一」：若兩支都執行，第二支的
        `bulk_enroll_returning` 因 `ON CONFLICT DO NOTHING` 不會新增、也就不寄信，結果相同。
        它守的是：此情形下若只走 `tags_add`（舊行為），只符合舊配對的人會被漏掉。
        """
        from datetime import timedelta

        from tests.integration.et._tag_pairs import audiences_req, new_tag, pair_user, role_pair

        uid = await _user(db, "t_ra07")
        ctx = await _published_course(client, db, uid)
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_start_at=utcnow() - timedelta(days=30), open_end_at=utcnow() - timedelta(days=1))
        )
        # 期間已過時被貼上**既有**配對的人（貼標追溯排除視同關閉課程，故沒被帶入）
        old_role = await _tag(db, f"標籤{ctx['course_id']}")
        old_match = await _user(db, "s_ra07a", role=ROLE_STUDENT)
        await pair_user(db, old_match, old_role)
        # 本次 PUT 才新增的配對與其相符者
        new_role = await new_tag(db, "職位_ra07")
        new_match = await _user(db, "s_ra07b", role=ROLE_STUDENT)
        await pair_user(db, new_match, new_role)
        db.expire_all()

        detail = (await client.get(f"{_COURSES}/{ctx['course_id']}", headers=_bearer(uid))).json()
        r = await client.put(
            f"{_COURSES}/{ctx['course_id']}",
            json={
                "course_name": detail["course_name"],
                "open_start_at": detail["open_start_at"],
                "open_end_at": _future(200),
                "audiences": [*audiences_req(detail), await role_pair(db, new_role)],
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 204, r.text
        for student in (old_match, new_match):
            assert await self._enrollment(db, student, ctx["course_id"]) is not None, student
            assert len(await self._pending_invites(db, f"{student}@edms.local")) == 1, student

    async def test_未復活的一般編輯不依全部配對重新帶入(self, client, db) -> None:
        """只有「復活」才依全部配對帶入；一般 PUT 維持只補本次新增的配對（FR-ET-US8-04）。"""
        from tests.integration.et._tag_pairs import audiences_req, pair_user

        uid = await _user(db, "t_ra06")
        ctx = await _published_course(client, db, uid)
        # 發布後才被貼上既有配對的人——這條路徑另有出口（貼標追溯），一般編輯不該順手帶入
        existing_role = await _tag(db, f"標籤{ctx['course_id']}")
        student = await _user(db, "s_ra06", role=ROLE_STUDENT)
        await pair_user(db, student, existing_role)

        detail = (await client.get(f"{_COURSES}/{ctx['course_id']}", headers=_bearer(uid))).json()
        r = await client.put(
            f"{_COURSES}/{ctx['course_id']}",
            json={
                "course_name": "改名",
                "open_start_at": detail["open_start_at"],
                "open_end_at": detail["open_end_at"],
                "audiences": audiences_req(detail),
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )

        assert r.status_code == 204, r.text
        assert await self._enrollment(db, student, ctx["course_id"]) is None
