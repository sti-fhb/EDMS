"""管理者代為轉讓課程擁有者（ET-13 / US1 補強 / #303）。

`ET_COURSE.OWNER_ID` 原則上**永久不可變更**（`data-model` §ET_COURSE 第 7 欄），管理者
代為轉讓是明訂的唯一例外（`spec.md:177`），需**雙寫**：`ET_OWNER_TRANSFER` 業務紀錄
（append-only）+ `DP_AUDIT_LOG`（`FUNC_NAME=ET-OWNER`，已列於 `spec.md:218` 稽核來源
功能碼表）。

## 🔴 本檔最重要的一組測試是授權邊界

轉讓是 ET **第一支 admin-only 端點**，也是第一個**刻意繞過 `ensure_owner`** 的寫入
（管理者轉讓的正是他不擁有的課程）。這兩件事疊起來的風險是：漏掉角色閘就變成「任何
教師都能搬走任何人的課程」，而擁有權檢核擋不住他——因為那道檢核已經被刻意移除了。

#288 的 Security Review 剛發現 `PUT` / `DELETE /courses/{id}` 漏掉 `require_et_roles`
（已開 #301），且**沒有任何測試變紅**，因為那些測試全用教師帳號跑。本檔的
`TestAuthorization` 就是為了不重演。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.users.models import DpUser
from app.et.constants import ITEM_MATERIAL, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER
from app.et.course.models import EtCourse
from app.et.invitation.models import EtOwnerTransfer
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *roles: str) -> str:
    """建使用者並賦予**零至多個** ET 角色。

    支援多角色是必要的：管理者常同時具教師角色，而「`require_et_roles(ET_ADMIN)` 只看
    有無 ADMIN」這件事需要一位兼具兩者的人來驗（見 `test_兼具教師角色的管理者可轉讓`）。
    零角色用於驗 `get_et_context` 那一層。
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
    for role in roles:
        db.add(
            EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
        )
    await db.flush()
    return user_id


async def _course(client, db, owner: str) -> dict:
    """一門草稿課程（1 章節 + 1 教材）。

    轉讓**不限課程狀態**——`spec.md:177` 的情境是「擁有者離職」，那與課程發布與否無關。
    故此處不發布，省掉標籤自動邀請的副作用。
    """
    created = await client.post(_COURSES, json={"course_name": "採血作業訓練"}, headers=_bearer(owner))
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(owner))
    assert ch.status_code == 201, ch.text
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(owner),
    )
    assert item.status_code == 201, item.text
    return {"course_id": cid, "version": created.json()["version"]}


async def _course_row(db, course_id: int) -> EtCourse:
    db.expire_all()
    row = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
    assert row is not None
    return row


async def _transfers(db, course_id: int) -> list[EtOwnerTransfer]:
    rows = await db.scalars(
        select(EtOwnerTransfer).where(EtOwnerTransfer.course_id == course_id).order_by(EtOwnerTransfer.transfer_id)
    )
    return list(rows.all())


async def _transfer(client, course_id: int, *, actor: str, to_owner: str, version: int, reason: str = "原教師離職"):
    return await client.post(
        f"{_COURSES}/{course_id}/transfer-owner",
        json={"to_owner_id": to_owner, "reason": reason, "version": version},
        headers=_bearer(actor),
    )


class TestTransfer:
    async def test_管理者可轉讓他人課程(self, client, db) -> None:
        """AC：管理者可執行轉讓。

        🔴 **管理者不是擁有者**——這正是本端點刻意不呼叫 `ensure_owner` 的理由。若日後
        有人「順手」把擁有權檢核加回來，這條會紅。
        """
        admin = await _user(db, "a_tr01", ROLE_ADMIN)
        owner = await _user(db, "t_tr01", ROLE_TEACHER)
        receiver = await _user(db, "t_tr01b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 200, r.text
        assert r.json()["owner_id"] == receiver
        assert (await _course_row(db, ctx["course_id"])).owner_id == receiver

    async def test_回傳版本與DB實際值一致(self, client, db) -> None:
        """以 `RETURNING` 取值，不由呼叫端自行 `+1`。

        ORM-enabled UPDATE 會同步 identity map，手上的物件 `version` 執行後**已是新值**，
        再 `+1` 會回給前端一個比 DB 大 1 的版本，而前端下一次帶它寫入必然 409。
        #288 修過 `publish` 的同一個形狀。
        """
        admin = await _user(db, "a_tr02", ROLE_ADMIN)
        owner = await _user(db, "t_tr02", ROLE_TEACHER)
        receiver = await _user(db, "t_tr02b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        assert r.json()["version"] == (await _course_row(db, ctx["course_id"])).version

    async def test_寫入轉讓紀錄(self, client, db) -> None:
        """`ET_OWNER_TRANSFER` append-only：轉讓前後擁有者、原因、執行管理者、時間。"""
        admin = await _user(db, "a_tr03", ROLE_ADMIN)
        owner = await _user(db, "t_tr03", ROLE_TEACHER)
        receiver = await _user(db, "t_tr03b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        await _transfer(
            client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"], reason="原教師轉調單位"
        )

        rows = await _transfers(db, ctx["course_id"])
        assert len(rows) == 1
        assert rows[0].from_owner_id == owner
        assert rows[0].to_owner_id == receiver
        assert rows[0].reason == "原教師轉調單位"
        assert rows[0].executed_by == admin, "執行者是管理者，不是任一方擁有者"
        assert rows[0].executed_at is not None

    async def test_寫入平台稽核且訊息不含動態值(self, client, db) -> None:
        """`spec.md:177` 要求**兩者都寫**；`spec.md:218` 明列 `FUNC_NAME=ET-OWNER`。

        `description` 依 `sti-error-codes` 不得嵌入動態值——轉讓原因、from / to 等
        動態內容落在 `ET_OWNER_TRANSFER` 的欄位裡，那張表本來就是為此存在的。
        """
        admin = await _user(db, "a_tr04", ROLE_ADMIN)
        owner = await _user(db, "t_tr04", ROLE_TEACHER)
        receiver = await _user(db, "t_tr04b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        await _transfer(
            client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"], reason="原教師離職"
        )

        rows = (
            await db.scalars(
                select(DpAuditLog).where(
                    DpAuditLog.func_name == "ET-OWNER", DpAuditLog.target_id == str(ctx["course_id"])
                )
            )
        ).all()
        assert len(rows) == 1
        # 操作者落在 `CREATED_USER`（`AuditLogBaseModel`），`DP_AUDIT_LOG` 無 operator_id 欄
        assert rows[0].created_user == admin
        assert rows[0].source_ip is not None, "關係到全部在籍學員的破例變更，須留來源 IP"
        assert receiver not in (rows[0].description or ""), "不得嵌入使用者 ID"
        # `spec.md:177` 要求 DP_AUDIT_LOG 記錄轉讓人 / 接收人。它們走 before/after
        # （會併入鏈式 ROW_HASH、且是 CSV 匯出實際含有的欄位），不是 description。
        assert owner in (rows[0].before_value or "")
        assert receiver in (rows[0].after_value or "")
        assert "原教師離職" not in (rows[0].after_value or ""), "自由文字留在 ET_OWNER_TRANSFER"
        assert "原教師離職" not in (rows[0].description or ""), "原因落在 ET_OWNER_TRANSFER，不進 description"

    async def test_轉讓後擁有權易主(self, client, db) -> None:
        """AC：新擁有者可編輯，原擁有者僅可閱覽。

        `is_owner` 由 `OWNER_ID` 導出，故轉讓完成的當下就生效，**無需額外程式碼**。
        這條測試釘住的正是「沒有恢復邏輯」這件事。
        """
        admin = await _user(db, "a_tr05", ROLE_ADMIN)
        owner = await _user(db, "t_tr05", ROLE_TEACHER)
        receiver = await _user(db, "t_tr05b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        as_receiver = await client.get(f"{_COURSES}/{ctx['course_id']}", headers=_bearer(receiver))
        as_old = await client.get(f"{_COURSES}/{ctx['course_id']}", headers=_bearer(owner))
        assert as_receiver.json()["is_owner"] is True
        assert as_old.json()["is_owner"] is False

        # 原擁有者的寫入應被擋下（403 `ET_COURSE_002`）
        blocked = await client.post(
            f"{_COURSES}/{ctx['course_id']}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(owner)
        )
        assert blocked.status_code == 403
        assert blocked.json()["error_code"] == "ET_COURSE_002"

    async def test_可重複轉讓且每次都留紀錄(self, client, db) -> None:
        """轉讓可逆（再轉回去即可）——這是 SA Q2 裁示 A「不檢核原擁有者是否失能」的
        理由之一：誤轉讓不是不可回復的事故。
        """
        admin = await _user(db, "a_tr06", ROLE_ADMIN)
        owner = await _user(db, "t_tr06", ROLE_TEACHER)
        receiver = await _user(db, "t_tr06b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        first = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])
        second = await _transfer(
            client,
            ctx["course_id"],
            actor=admin,
            to_owner=owner,
            version=first.json()["version"],
            reason="轉調回原單位",
        )

        assert second.status_code == 200, second.text
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner
        rows = await _transfers(db, ctx["course_id"])
        assert len(rows) == 2, "append-only：兩次轉讓兩筆紀錄"
        assert (rows[1].from_owner_id, rows[1].to_owner_id) == (receiver, owner)


class TestValidation:
    async def test_接收者不具教師角色回422(self, client, db) -> None:
        """`ET_OWNER_001`：課程擁有者必須是教師，否則轉讓後沒有人能編輯這門課。"""
        admin = await _user(db, "a_va01", ROLE_ADMIN)
        owner = await _user(db, "t_va01", ROLE_TEACHER)
        student = await _user(db, "s_va01", ROLE_STUDENT)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=student, version=ctx["version"])

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_OWNER_001"
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner
        assert await _transfers(db, ctx["course_id"]) == [], "失敗不留紀錄"

    async def test_接收者已是擁有者回409(self, client, db) -> None:
        """`ET_OWNER_002`：不是「重複操作無害」——它會寫一筆 from == to 的紀錄，
        讓稽核出現一筆什麼都沒改的變更。
        """
        admin = await _user(db, "a_va02", ROLE_ADMIN)
        owner = await _user(db, "t_va02", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=owner, version=ctx["version"])

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_OWNER_002"
        assert await _transfers(db, ctx["course_id"]) == []

    @pytest.mark.parametrize(
        ("field", "value"),
        [("deleted", 1), ("status", "INACTIVE")],
    )
    async def test_接收者帳號已刪或已停用回422(self, client, db, field: str, value) -> None:
        """接收者的**帳號狀態**也要看，不只是 `ET_USER_ROLE`。

        `get_jwt_payload` 每個請求都擋掉 deleted / 非 `ACTIVE` 的帳號，所以轉給這種人
        的結果是**他永遠登不進來** —— 正好造出這道檢核要避免的東西：一門沒有人能編輯
        的課程。而「離職接手」正是最可能踏進去的情境。

        ⚠️ 與 #303 SA Q2 裁示 A 無關：那條談的是**原**擁有者是否須已離職；此處是
        **接收者**能不能用，是不同的人、不同的問題。
        """
        from sqlalchemy import update as sa_update

        admin = await _user(db, f"a_va07{field[:3]}", ROLE_ADMIN)
        owner = await _user(db, f"t_va07{field[:3]}", ROLE_TEACHER)
        receiver = await _user(db, f"t_va07{field[:3]}b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)
        await db.execute(sa_update(DpUser).where(DpUser.user_id == receiver).values(**{field: value}))
        await db.flush()

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_OWNER_001"
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner

    async def test_接收者不存在回422(self, client, db) -> None:
        """查無帳號者自然不具教師角色，走同一個碼——不另分一碼，因為管理者的下一步
        相同（換一個人），且不揭露「這個 ID 存不存在」。
        """
        admin = await _user(db, "a_va03", ROLE_ADMIN)
        owner = await _user(db, "t_va03", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner="nobody", version=ctx["version"])

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_OWNER_001"

    @pytest.mark.parametrize("reason", ["", "   "])
    async def test_轉讓原因必填(self, client, db, reason: str) -> None:
        """AC：必填轉讓原因。它是 SA Q2 裁示 A 之下**唯一的事前控制**，空白等同未填。"""
        admin = await _user(db, f"a_va04{len(reason)}", ROLE_ADMIN)
        owner = await _user(db, f"t_va04{len(reason)}", ROLE_TEACHER)
        receiver = await _user(db, f"t_va04{len(reason)}b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(
            client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"], reason=reason
        )

        assert r.status_code == 422, r.text
        assert await _transfers(db, ctx["course_id"]) == []

    async def test_版本不符回409(self, client, db) -> None:
        """兩位管理者同時轉讓時的第二位——樂觀鎖攔在 UPDATE 的 WHERE 上。"""
        admin = await _user(db, "a_va05", ROLE_ADMIN)
        owner = await _user(db, "t_va05", ROLE_TEACHER)
        receiver = await _user(db, "t_va05b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"] + 99)

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_LOCK_001"
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner
        assert await _transfers(db, ctx["course_id"]) == [], "版本不符不留紀錄（同一交易全部回滾）"

    async def test_查無課程回404(self, client, db) -> None:
        admin = await _user(db, "a_va06", ROLE_ADMIN)
        await _user(db, "t_va06", ROLE_TEACHER)

        r = await _transfer(client, 999_999_999, actor=admin, to_owner="t_va06", version=0)

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_COURSE_001"


class TestTeacherOptions:
    """`GET /api/et/teachers`——轉讓視窗「接收教師」下拉的資料來源。

    規劃階段漏列了這支：`issues.md` T115「管理者選擇課程 + 接收教師」需要一份教師清單，
    而 ET 原本沒有任何列教師的端點（`GET /api/dp/users` 是 DP 的分頁端點，且不帶
    `ET_USER_ROLE`，篩不出誰是 ET 教師）。
    """

    async def test_列出啟用中的教師(self, client, db) -> None:
        admin = await _user(db, "a_to01", ROLE_ADMIN)
        teacher = await _user(db, "t_to01", ROLE_TEACHER)
        await _user(db, "s_to01", ROLE_STUDENT)

        r = await client.get("/api/et/teachers", headers=_bearer(admin))

        assert r.status_code == 200, r.text
        ids = [row["user_id"] for row in r.json()]
        assert teacher in ids
        assert "s_to01" not in ids, "學員不是可接收的對象"

    async def test_回傳姓名供下拉顯示(self, client, db) -> None:
        """只回 `user_id` 的話管理者得自己記住誰是誰——下拉要顯示得出人名。"""
        admin = await _user(db, "a_to02", ROLE_ADMIN)
        teacher = await _user(db, "t_to02", ROLE_TEACHER)

        r = await client.get("/api/et/teachers", headers=_bearer(admin))

        row = next(x for x in r.json() if x["user_id"] == teacher)
        assert row["user_name"] == f"測試{teacher}"

    async def test_停用角色者不列出(self, client, db) -> None:
        """比照 `_has_teacher_role`：停用的角色不算有，否則下拉會列出一個選了會 422 的人。"""
        from sqlalchemy import update as sa_update

        admin = await _user(db, "a_to03", ROLE_ADMIN)
        teacher = await _user(db, "t_to03", ROLE_TEACHER)
        await db.execute(sa_update(EtUserRole).where(EtUserRole.user_id == teacher).values(is_active=False))
        await db.flush()

        r = await client.get("/api/et/teachers", headers=_bearer(admin))

        assert teacher not in [row["user_id"] for row in r.json()]

    async def test_非管理者不可列教師(self, client, db) -> None:
        """教師姓名清單是輕度個資，且這支只為轉讓而存在——與轉讓端點同一道閘。"""
        teacher = await _user(db, "t_to04", ROLE_TEACHER)

        r = await client.get("/api/et/teachers", headers=_bearer(teacher))

        assert r.status_code == 403, r.text


class TestAuthorization:
    """🔴 admin-only 的閘。漏掉時擁有權檢核**擋不住**——它已被刻意移除。"""

    async def test_教師角色轉讓回403(self, client, db) -> None:
        teacher = await _user(db, "t_au01", ROLE_TEACHER)
        owner = await _user(db, "t_au01o", ROLE_TEACHER)
        receiver = await _user(db, "t_au01b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=teacher, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 403, r.text
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner

    async def test_擁有者本人亦不可自行轉讓(self, client, db) -> None:
        """`plan.md:221`：**一般教師不可主動轉讓**。

        這條是最容易被漏掉的一種：擁有者對自己的課程在其他所有端點都有權限，唯獨轉讓
        必須經管理者。若誤用 `require_et_roles(ET_TEACHER, ET_ADMIN)`（本 router 其餘
        端點的形狀），這條會紅。
        """
        owner = await _user(db, "t_au02", ROLE_TEACHER)
        receiver = await _user(db, "t_au02b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=owner, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 403, r.text
        assert (await _course_row(db, ctx["course_id"])).owner_id == owner

    async def test_學員角色轉讓回403(self, client, db) -> None:
        student = await _user(db, "s_au03", ROLE_STUDENT)
        owner = await _user(db, "t_au03", ROLE_TEACHER)
        receiver = await _user(db, "t_au03b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=student, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 403, r.text

    async def test_兼具教師角色的管理者可轉讓(self, client, db) -> None:
        """`require_et_roles(ET_ADMIN)` 只看**有無** ADMIN，與是否同時具 TEACHER 無關。

        實務上管理者常同時掛教師角色（要自己建課程）。若實作誤寫成「只有 ADMIN、不能
        有 TEACHER」，這條會紅。
        """
        admin = await _user(db, "a_au04", ROLE_ADMIN, ROLE_TEACHER)
        owner = await _user(db, "t_au04", ROLE_TEACHER)
        receiver = await _user(db, "t_au04b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 200, r.text

    async def test_管理者被停用角色後轉讓回403(self, client, db) -> None:
        """`require_et_roles` 比對 `IS_ACTIVE`——停用的角色不算有。"""
        from sqlalchemy import update as sa_update

        admin = await _user(db, "a_au05", ROLE_ADMIN)
        owner = await _user(db, "t_au05", ROLE_TEACHER)
        receiver = await _user(db, "t_au05b", ROLE_TEACHER)
        ctx = await _course(client, db, owner)
        await db.execute(sa_update(EtUserRole).where(EtUserRole.user_id == admin).values(is_active=False))
        await db.flush()

        r = await _transfer(client, ctx["course_id"], actor=admin, to_owner=receiver, version=ctx["version"])

        assert r.status_code == 403, r.text
