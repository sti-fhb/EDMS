"""ET10 核可查詢（US17 / #385）——兩視角的可見範圍與查詢行為。

## 與 `test_approval_query_rules.py`（unit）的分工

那支證明「條件被正確組進 SQL」，本檔證明「條件在真的資料上篩對」。兩層都要：unit
擋得住結合順序被改壞（`A AND B OR C` → `A AND (B OR C)`），但擋不住「條件正確卻忘了
JOIN `ET_COURSE`」這種只有真 DB 才看得出來的錯。

## 資料佈局

三門課、三位教師，讓「自己的課 vs 別人的課」× 「PASS / FAIL / 撤銷」都有對照組：

| 課程 | owner | 學員 | 核可結果 |
|---|---|---|---|
| 課 A | t_own | 林佳蓉 | PASS（未撤銷）|
| 課 B | t_other | 林佳蓉 | PASS（未撤銷）|
| 課 C | t_other | 林佳蓉 | FAIL |
| 課 D | t_other | 林佳蓉 | PASS **但已撤銷** |
| 課 A | t_own | 王大明 | FAIL |

以 `t_own` 的視角查「林」時，裁示 C 要求看得到 A、B，看不到 C、D。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.approval.models import EtApproval
from app.et.constants import (
    APPROVAL_FAIL,
    APPROVAL_PASS,
    COURSE_PUBLISHED,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
)
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_QUERY = "/api/et/approvals"
_MINE = "/api/et/approvals/mine"


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


async def _course(db, *, owner: str, name: str) -> int:
    now = utcnow()
    course = EtCourse(
        course_name=name,
        status=COURSE_PUBLISHED,
        owner_id=owner,
        open_start_at=now - timedelta(days=1),
        open_end_at=now + timedelta(days=30),
        version=0,
        require_approval=True,
        urgent_remind_sent=False,
        created_user=owner,
        created_date=now,
        deleted=0,
    )
    db.add(course)
    await db.flush()
    return course.course_id


async def _approval(
    db,
    *,
    course_id: int,
    user_id: str,
    result: str,
    approved_by: str,
    revoked_by: str | None = None,
    revoke_reason: str | None = None,
    note: str | None = None,
) -> None:
    now = utcnow()
    db.add(
        EtApproval(
            course_id=course_id,
            user_id=user_id,
            result=result,
            result_note=note,
            is_revoked=revoked_by is not None,
            revoke_reason=revoke_reason,
            approved_by=approved_by,
            approved_at=now,
            revoked_by=revoked_by,
            revoked_at=now if revoked_by else None,
            version=0,
            created_user=approved_by,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _fixture(db) -> dict:
    """建立檔頭表格所述的資料佈局。"""
    own = await _user(db, "t_own", name="王主任")
    other = await _user(db, "t_other", name="陳教官")
    admin = await _user(db, "adm01", roles=(ROLE_ADMIN,), name="李管理員")
    lin = await _user(db, "s_lin", roles=(ROLE_STUDENT,), name="林佳蓉")
    wang = await _user(db, "s_wang", roles=(ROLE_STUDENT,), name="王大明")

    a = await _course(db, owner=own, name="採血作業新進人員訓練")
    b = await _course(db, owner=other, name="成分製備標準作業教學")
    c = await _course(db, owner=other, name="捐血人健康評估標準教學")
    d = await _course(db, owner=other, name="血品安全與品保概論")

    await _approval(db, course_id=a, user_id=lin, result=APPROVAL_PASS, approved_by=own)
    await _approval(db, course_id=b, user_id=lin, result=APPROVAL_PASS, approved_by=other)
    await _approval(db, course_id=c, user_id=lin, result=APPROVAL_FAIL, approved_by=other, note="實機操作需再加強")
    await _approval(
        db,
        course_id=d,
        user_id=lin,
        result=APPROVAL_PASS,
        approved_by=other,
        revoked_by=admin,
        revoke_reason="核可對象誤植",
    )
    await _approval(db, course_id=a, user_id=wang, result=APPROVAL_FAIL, approved_by=own)
    return {"own": own, "other": other, "admin": admin, "lin": lin, "wang": wang, "a": a, "b": b, "c": c, "d": d}


def _names(payload) -> set[str]:
    return {row["course_name"] for row in payload["data"]}


class TestTeacherScope:
    """SA Q1 裁示 C：通過看全部、不通過與已撤銷僅限自己 owner 的課程。"""

    async def test_教師查得他人課程的通過紀錄(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert "成分製備標準作業教學" in _names(r.json()), "他人課程的通過紀錄應可見（裁示 C）"

    async def test_教師查不到他人課程的不通過(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))
        assert "捐血人健康評估標準教學" not in _names(r.json())

    async def test_教師查不到他人課程已撤銷的通過(self, client, db) -> None:
        """🔴 被撤銷的通過其 `RESULT` 仍是 PASS——只依 RESULT 分流會讓撤銷原因外洩。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))
        body = r.json()
        assert "血品安全與品保概論" not in _names(body)
        assert "核可對象誤植" not in r.text, "撤銷原因不得出現在他人課程的回應中"

    async def test_教師看得到自己課程的不通過(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "王大明"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["result"] for row in rows] == [APPROVAL_FAIL]
        assert rows[0]["result_note"] is None or "加強" not in (rows[0]["result_note"] or "")

    async def test_教師視角的總筆數不含看不到的紀錄(self, client, db) -> None:
        """🔴 釘住「範圍判定進 WHERE 而非後篩」。

        若改成取出後在 Python 過濾，`meta.total` 會是過濾**前**的筆數——教師看到
        「共 4 筆」卻只翻得出 2 筆，而且不會有任何錯誤訊息。
        """
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))
        body = r.json()
        assert body["meta"]["total"] == len(body["data"]) == 2


class TestResultFilterInteraction:
    """`result` 篩選參數 × 可見範圍條件的交互作用。

    🔴 這組是 review 時才想到要補的：`visible` 是一個 `OR`，而 `result` 是另一個 `AND`
    上去的條件。兩者相乘之後的實際範圍不是讀一眼就看得出來的——推理說「`AND result=FAIL`
    會讓 OR 的左側（要求 PASS）恆假、於是收斂成僅自己 owner」，但**推理不是驗證**。
    """

    async def test_教師篩不通過時仍只看得到自己課程的(self, client, db) -> None:
        """若 SQLAlchemy 沒替 `visible` 的 OR 加括號，這條會撈到他人課程的不通過。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林", "result": "FAIL"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == set(), "林佳蓉的不通過只在他人課程，教師不該看到"

    async def test_教師篩通過時看得到自己課程已撤銷的(self, client, db) -> None:
        """自己 owner 的課程不受結果分流限制——已撤銷的通過仍在可見範圍內。

        ⚠️ 必須另建一門 `own` 的課：`(COURSE_ID, USER_ID)` 為**全表唯一**，一位學員於
        一門課至多一筆核可，不能在 fixture 既有的課 A 上再給王大明加一筆。
        """
        f = await _fixture(db)
        e = await _course(db, owner=f["own"], name="輸血反應處置流程培訓")
        await _approval(
            db,
            course_id=e,
            user_id=f["wang"],
            result=APPROVAL_PASS,
            approved_by=f["own"],
            revoked_by=f["own"],
            revoke_reason="自己課程的撤銷",
        )
        r = await client.get(_QUERY, params={"user_name": "王大明", "result": "PASS"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["is_revoked"] for row in rows] == [True]
        assert rows[0]["revoke_reason"] == "自己課程的撤銷"

    async def test_篩選值不在值域時回422(self, client, db) -> None:
        """`result` 走 router 的 pattern 驗證，不合法的值不該被當成「不篩」而放行全部。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林", "result": "WHATEVER"}, headers=_bearer(f["own"]))
        assert r.status_code == 422


class TestResultNoteRedaction:
    """🔴 `RESULT_NOTE` 只對該課程 owner 與管理者顯示（SA 裁示 2026-09-21）。

    裁示 C 原本只切**結果**維度，沒切**欄位**維度。而 `ApproveReq.result_note` 明文允許
    `PASS` 附備註——負面評語只要掛在通過上，就會隨「通過可查全部」流向全體教師。
    """

    async def _pass_with_note(self, db, f) -> None:
        """在**他人**課程給林佳蓉一筆帶備註的通過（教師依裁示 C 看得到這一列）。"""
        e = await _course(db, owner=f["other"], name="輸血反應處置流程培訓")
        await _approval(
            db,
            course_id=e,
            user_id=f["lin"],
            result=APPROVAL_PASS,
            approved_by=f["other"],
            note="第二次補考才通過，單採操作仍不穩",
        )

    async def test_他人課程的通過備註對教師遮蔽(self, client, db) -> None:
        f = await _fixture(db)
        await self._pass_with_note(db, f)

        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "輸血反應處置流程培訓")
        assert row["result_note"] is None, "他人課程的考核評語不得回傳"
        assert "單採操作仍不穩" not in r.text, "評語不得以任何形式出現在回應中"

    async def test_自己課程的通過備註照常顯示(self, client, db) -> None:
        f = await _fixture(db)
        e = await _course(db, owner=f["own"], name="血袋判讀實務")
        await _approval(db, course_id=e, user_id=f["lin"], result=APPROVAL_PASS, approved_by=f["own"], note="操作熟練")

        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血袋判讀實務")
        assert row["result_note"] == "操作熟練"

    async def test_管理者看得到全部備註(self, client, db) -> None:
        f = await _fixture(db)
        await self._pass_with_note(db, f)

        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["admin"]))

        notes = {x["course_name"]: x["result_note"] for x in r.json()["data"]}
        assert notes["輸血反應處置流程培訓"] == "第二次補考才通過，單採操作仍不穩"
        assert notes["捐血人健康評估標準教學"] == "實機操作需再加強", "不通過的備註也照常"

    async def test_學員端本來就不含備註欄位(self, client, db) -> None:
        """學員端是**結構性**不含（`MyApprovalRow` 沒這個欄位），不倚賴本次的遮蔽邏輯。"""
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["lin"]))
        assert all("result_note" not in row for row in r.json()["data"])


class TestAdminScope:
    async def test_管理者可查非自己建立課程的全部紀錄(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {
            "採血作業新進人員訓練",
            "成分製備標準作業教學",
            "捐血人健康評估標準教學",
            "血品安全與品保概論",
        }

    async def test_管理者看得到撤銷原因與撤銷人(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["admin"]))
        revoked = next(row for row in r.json()["data"] if row["is_revoked"])
        assert revoked["revoke_reason"] == "核可對象誤植"
        assert revoked["revoked_by_name"] == "李管理員"
        assert revoked["revoked_at"] is not None


class TestQueryBehaviour:
    async def test_回應含課程名稱與核可人姓名(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林佳蓉"}, headers=_bearer(f["admin"]))
        row = next(x for x in r.json()["data"] if x["course_name"] == "採血作業新進人員訓練")
        assert row["user_name"] == "林佳蓉"
        assert row["approved_by_name"] == "王主任"
        assert row["approved_at"] is not None

    async def test_姓名未填回422(self, client, db) -> None:
        """SA Q2 裁示 A：姓名必填——留白查全部沒有對應需求，且會傾印員工名冊。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, headers=_bearer(f["admin"]))
        assert r.status_code == 422

    async def test_姓名只有空白視為未填(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "   "}, headers=_bearer(f["admin"]))
        assert r.status_code == 422

    async def test_姓名輸入百分號不得變成查全部(self, client, db) -> None:
        """🔴 未跳脫時 `%` 會讓 Q2 的必填形同虛設，**且沒有任何錯誤訊息**。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "%"}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == [], "`%` 應被當成字面字元，查無姓名含 % 的人"

    async def test_底線也要跳脫(self, client, db) -> None:
        """`_` 是 LIKE 的單字元萬用字元，與 `%` 同屬必須跳脫的對象。"""
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "_"}, headers=_bearer(f["admin"]))
        assert r.json()["data"] == []

    async def test_學員不可使用教師端查詢(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["lin"]))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"


class TestStudentSelfView:
    async def test_只回自己已通過且未撤銷的課程(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["lin"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"採血作業新進人員訓練", "成分製備標準作業教學"}

    async def test_不通過與已撤銷不出現(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["lin"]))
        names = _names(r.json())
        assert "捐血人健康評估標準教學" not in names, "不通過不得出現"
        assert "血品安全與品保概論" not in names, "已撤銷的通過不得出現"

    async def test_不回傳結果備註與撤銷欄位(self, client, db) -> None:
        """🔴 **後端不回傳**，不是前端不渲染。

        `result_note` 是教師寫的考核評語、撤銷欄位承載負面判斷；`FR-ET-US17-03` 明訂
        學員端不顯示。若靠前端過濾，打開 devtools 就看得到。
        """
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["lin"]))
        row = r.json()["data"][0]
        for banned in ("result_note", "is_revoked", "revoke_reason", "revoked_by_name", "revoked_at", "user_name"):
            assert banned not in row, f"學員端回應不得含 {banned}"

    async def test_查不到他人的紀錄(self, client, db) -> None:
        """端點不收任何 `user_id` 參數——對象一律取自 token，沒有可竄改的參數。"""
        f = await _fixture(db)
        r = await client.get(_MINE, params={"user_id": f["lin"]}, headers=_bearer(f["wang"]))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == [], "王大明只有不通過紀錄，不得因帶參數而看到林佳蓉的"

    async def test_無已通過課程時回空清單(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["wang"]))
        assert r.status_code == 200
        assert r.json()["data"] == []
        assert r.json()["meta"]["total"] == 0

    async def test_教師也能查自己的已通過課程(self, client, db) -> None:
        """端點只掛 `get_et_context`——教師同時也是學員時，這條路徑照常可用。"""
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text


class TestSoftDeleteAndIsolation:
    async def test_不回傳已軟刪除的核可紀錄(self, client, db) -> None:
        f = await _fixture(db)
        row = await db.scalar(select(EtApproval).where(EtApproval.course_id == f["a"], EtApproval.user_id == f["lin"]))
        row.deleted = 1
        await db.flush()

        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["admin"]))
        assert "採血作業新進人員訓練" not in _names(r.json())

    async def test_不回傳已軟刪除課程的核可紀錄(self, client, db) -> None:
        f = await _fixture(db)
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == f["a"]))
        course.deleted = 1
        await db.flush()

        r = await client.get(_QUERY, params={"user_name": "林"}, headers=_bearer(f["admin"]))
        assert "採血作業新進人員訓練" not in _names(r.json())
