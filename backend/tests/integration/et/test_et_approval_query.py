"""ET04 核可查詢（US17 / #385）——兩視角的可見範圍與查詢行為。

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

_QUERY = "/api/et/approvals/search"
_MINE = "/api/et/approvals/mine"
_FILTER_COURSES = "/api/et/approvals/filter-courses"


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
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert "成分製備標準作業教學" in _names(r.json()), "他人課程的通過紀錄應可見（裁示 C）"

    async def test_教師查不到他人課程的不通過(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert "捐血人健康評估標準教學" not in _names(r.json())

    async def test_教師查不到他人課程已撤銷的通過(self, client, db) -> None:
        """🔴 被撤銷的通過其 `RESULT` 仍是 PASS——只依 RESULT 分流會讓撤銷原因外洩。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        body = r.json()
        assert "血品安全與品保概論" not in _names(body)
        assert "核可對象誤植" not in r.text, "撤銷原因不得出現在他人課程的回應中"

    async def test_教師看得到自己課程的不通過(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "王大明"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["result"] for row in rows] == [APPROVAL_FAIL]
        assert rows[0]["result_note"] is None or "加強" not in (rows[0]["result_note"] or "")

    async def test_教師視角的總筆數不含看不到的紀錄(self, client, db) -> None:
        """🔴 釘住「範圍判定進 WHERE 而非後篩」。

        若改成取出後在 Python 過濾，`meta.total` 會是過濾**前**的筆數——教師看到
        「共 4 筆」卻只翻得出 2 筆，而且不會有任何錯誤訊息。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
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
        r = await client.post(_QUERY, json={"keyword": "林", "result": "FAIL"}, headers=_bearer(f["own"]))
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
        r = await client.post(_QUERY, json={"keyword": "王大明", "result": "PASS"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["is_revoked"] for row in rows] == [True]
        assert rows[0]["revoke_reason"] == "自己課程的撤銷"

    async def test_篩選值不在值域時回422(self, client, db) -> None:
        """`result` 走 router 的 pattern 驗證，不合法的值不該被當成「不篩」而放行全部。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "result": "WHATEVER"}, headers=_bearer(f["own"]))
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

        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "輸血反應處置流程培訓")
        assert row["result_note"] is None, "他人課程的考核評語不得回傳"
        assert "單採操作仍不穩" not in r.text, "評語不得以任何形式出現在回應中"

    async def test_自己課程的通過備註照常顯示(self, client, db) -> None:
        f = await _fixture(db)
        e = await _course(db, owner=f["own"], name="血袋判讀實務")
        await _approval(db, course_id=e, user_id=f["lin"], result=APPROVAL_PASS, approved_by=f["own"], note="操作熟練")

        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血袋判讀實務")
        assert row["result_note"] == "操作熟練"

    async def test_管理者看得到全部備註(self, client, db) -> None:
        f = await _fixture(db)
        await self._pass_with_note(db, f)

        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))

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
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {
            "採血作業新進人員訓練",
            "成分製備標準作業教學",
            "捐血人健康評估標準教學",
            "血品安全與品保概論",
        }

    async def test_管理者看得到撤銷原因與撤銷人(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        revoked = next(row for row in r.json()["data"] if row["is_revoked"])
        assert revoked["revoke_reason"] == "核可對象誤植"
        assert revoked["revoked_by_name"] == "李管理員"
        assert revoked["revoked_at"] is not None


class TestQueryBehaviour:
    async def test_回應含課程名稱與核可人姓名(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林佳蓉"}, headers=_bearer(f["admin"]))
        row = next(x for x in r.json()["data"] if x["course_name"] == "採血作業新進人員訓練")
        assert row["user_name"] == "林佳蓉"
        assert row["approved_by_name"] == "王主任"
        assert row["approved_at"] is not None

    async def test_關鍵字與課程皆未給回422(self, client, db) -> None:
        """#439 取代 SA Q2 裁示 A 的「姓名必填」——**目的未變**：留白仍不可查全部。

        ⚠️ 送 `json={}` 而非完全不帶 body。不帶 body 時 FastAPI 自己就會回 422
        （`COMMON_422`，因為 body 是必要參數），那條路徑根本到不了本規則——只斷言
        「status 是 422」會變成一條**驗什麼都會通過**的測試。故一併斷言 `error_code`。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={}, headers=_bearer(f["admin"]))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_APPROVAL_006"

    async def test_關鍵字只有空白且未選課程視為未給(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "   "}, headers=_bearer(f["admin"]))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_APPROVAL_006"

    async def test_姓名走query_string不被接受(self, client, db) -> None:
        """🔴 #391：查詢條件**只走 body**，query string 不是可接受的通道。

        本端點之所以是 POST，唯一理由就是不讓明文姓名進入網址——URL 會被沿路記下來，
        body 不會：

        | 記錄點 | 現況 |
        |---|---|
        | EDMS 自家 access log | 已處理（`$request_uri` 去尾 + uvicorn `--no-access-log`）|
        | **EDMS nginx `error_log`** | ⚠️ 記完整 request，而 nginx 的 error log 格式**不可自訂** |
        | **Cloudflare 請求日誌** | ⚠️ 記完整 URI，且不在本系統掌控範圍 |

        ⛔ 若日後有人為了「相容舊呼叫」補一個 `user_name: Query(...)` 的退路，姓名就
        又回到網址裡，而**功能會正常運作、沒有任何東西會紅**——本條就是那道紅線。
        """
        f = await _fixture(db)

        r = await client.post(f"{_QUERY}?user_name=林", headers=_bearer(f["admin"]))

        assert r.status_code == 422, "query string 不得成為 user_name 的來源"

    async def test_姓名輸入百分號不得變成查全部(self, client, db) -> None:
        """🔴 未跳脫時 `%` 會讓 Q2 的必填形同虛設，**且沒有任何錯誤訊息**。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "%"}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == [], "`%` 應被當成字面字元，查無姓名含 % 的人"

    async def test_底線也要跳脫(self, client, db) -> None:
        """`_` 是 LIKE 的單字元萬用字元，與 `%` 同屬必須跳脫的對象。

        🔴 **本條在 #436（加入 Email 比對）之後必須改寫，否則它失去鑑別力。**

        原本斷言「查 `_` 回空」——那在「只比對姓名」時成立（沒有人的姓名含底線）。
        但 fixture 的 Email 是 `s_lin@…` / `s_wang@…`，**兩個都含字面底線**，於是
        不論跳脫有沒有壞，查 `_` 都會回全部——**測試分不出兩種情形**。

        改為鑑別式：另建一位 Email **不含**底線的學員，查 `_` 時他必須**不**出現。
        跳脫若失效，`_` 會變成單字元萬用字元而命中他。
        """
        f = await _fixture(db)
        # Email 不含底線；姓名也不含，故只有「跳脫失效」才會讓他出現
        noun = await _user(db, "sxnoun", roles=(ROLE_STUDENT,), name="趙一")
        await _approval(db, course_id=f["a"], user_id=noun, result=APPROVAL_PASS, approved_by=f["own"])

        r = await client.post(_QUERY, json={"keyword": "_"}, headers=_bearer(f["admin"]))

        assert r.status_code == 200, r.text
        ids = {row["user_id"] for row in r.json()["data"]}
        assert noun not in ids, "`_` 應被當成字面字元；命中無底線的帳號代表跳脫失效"
        assert f["lin"] in ids, "含字面底線的 Email 應照常命中"

    async def test_學員不可使用教師端查詢(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["lin"]))
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

        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        assert "採血作業新進人員訓練" not in _names(r.json())

    async def test_不回傳已軟刪除課程的核可紀錄(self, client, db) -> None:
        f = await _fixture(db)
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == f["a"]))
        course.deleted = 1
        await db.flush()

        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        assert "採血作業新進人員訓練" not in _names(r.json())


class TestKeywordMatchesNameOrEmail:
    """#436：單一欄位可用**姓名或 Email** 查詢，擇一命中即可。

    同名同姓時姓名不足以定位，而 Email 是帳號的唯一鍵——手測正是為此回報。
    """

    async def test_以_email_查得到(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "s_lin@edms.local"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()), "以 Email 應查得到該學員的核可紀錄"

    async def test_email_部分比對也命中(self, client, db) -> None:
        """與姓名同為 `contains` 語意——教師記得帳號前半段就查得到。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "s_lin"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json())

    async def test_姓名仍照常查得到(self, client, db) -> None:
        """回歸護欄：加了 Email 不得讓姓名失效。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json())

    async def test_兩者皆不命中時回空(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "查無此人"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == []

    async def test_email_的萬用字元一樣要跳脫(self, client, db) -> None:
        """🔴 與姓名同一條理由：未跳脫時 `%` 等於「查全部」，而**沒有任何錯誤訊息**。

        ⚠️ 加了第二個比對欄位就多一個要跳脫的地方——`or_` 的任一邊漏跳脫，整條
        `or_` 就恆真。本條同時涵蓋兩邊（`%` 對姓名也不該命中）。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "%"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert r.json()["data"] == [], "`%` 必須被當成字面字元，不得變成查全部"


class TestEmailDomainIsNotSearchable:
    """#456：**單一常見字串不得命中全體**。

    `DP_USER.EMAIL` 為 `NOT NULL`，而全體使用者的網域是同一串字。改版前對整個 Email
    做 contains 比對，於是 `@` / `edms.local` / `local` 這類字串**單獨一個就命中全體**
    ——一次請求加翻頁即可取走可見範圍內的全部核可／完課紀錄。

    收斂後的語意是「**local part 做 contains，或完整 Email 做相等**」：
    相等最多命中一個人、不具列舉價值，所以把網域放回那一條是安全的。

    ⚠️ 本組與 `TestKeywordMatchesNameOrEmail` **成對**——那邊釘住「以完整 Email 查得到」
    與「local part 部分比對也命中」，少了那邊，把 Email 整條比對拿掉也會讓本組全綠。

    ⚠️ **這不是安全邊界**。它擋掉「打一個字就全撈」，擋不住有心人逐字掃；真正在收斂的
    是母體限制與角色受控（#392 裁示 C）。測試釘的是「成本不得退回一個請求」。
    """

    @pytest.mark.parametrize(
        "keyword",
        ["@", "edms.local", "local", "@edms", ".local"],
        ids=["at", "full_domain", "domain_word", "at_domain", "dot_domain"],
    )
    async def test_網域相關字串不得命中任何人(self, client, db, keyword: str) -> None:
        f = await _fixture(db)
        # 🔴 正向錨點不可省：同一組 fixture 以正常關鍵字查得到資料，否則下面的「空清單」
        # 可能只是因為根本沒有任何紀錄——那樣的斷言對任何實作都會通過。
        baseline = await client.post(_QUERY, json={"keyword": "s_lin"}, headers=_bearer(f["own"]))
        assert _names(baseline.json()), "錨點失敗：fixture 查不到資料，本測試沒有鑑別力"

        r = await client.post(_QUERY, json={"keyword": keyword}, headers=_bearer(f["own"]))

        assert r.status_code == 200, r.text
        assert r.json()["data"] == [], f"{keyword!r} 命中了紀錄——Email 比對又涵蓋了網域"

    async def test_管理者側同樣收斂(self, client, db) -> None:
        """⚠️ 母體最大的是管理者——教師側通過不代表管理者側也通過。

        關鍵字條件套在 `approval_side` 與 `completion_side` 兩側，而角色只影響課程範圍；
        但「兩側都套」這件事本身曾是 review 抓到的缺口，故對母體最大的角色另驗一次。
        """
        f = await _fixture(db)
        baseline = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        assert _names(baseline.json()), "錨點失敗：管理者查不到資料"

        r = await client.post(_QUERY, json={"keyword": "edms.local"}, headers=_bearer(f["admin"]))

        assert r.status_code == 200, r.text
        assert r.json()["data"] == []


class TestCourseFilter:
    """#439：關鍵字與課程「至少給一個」，課程單獨即可查。

    ## 為何這組非得是 integration

    「只給課程」這條路徑的正確性同時取決於三件只有真 DB 看得出來的事：`course_id`
    條件真的下推到 `WHERE`、`visible_clause` 仍與它 `AND` 相接、以及 `paginate()` 的
    `meta.total` 與資料用的是同一個 `stmt`。純函式那層（`test_approval_query_rules.py`）
    擋不住其中任何一件。
    """

    async def test_只給課程不給關鍵字可查出該課程的核可紀錄(self, client, db) -> None:
        """AC 1：解決「不知道有誰可以查」——教師常常正是不知道名單。

        ⭐ **課程名稱那條斷言是變異檢查逼出來的，不要拿掉。** 原本只斷言 `user_name`
        的集合，而拿掉 `course_id` 條件之後多出來的那筆是**林佳蓉在課 B**——收斂成 set
        之後與課 A 的兩人**一模一樣**，於是這條（AC 1 的主測試）在該變異下照樣通過。

        教訓不是「斷言寫得不夠多」，而是：**斷言的是結果，而結果可以由不只一個原因
        達成**。可操作的檢查法是問「如果課程條件從來沒被套用，這條斷言還會成立嗎？」
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["a"]}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert {row["user_name"] for row in rows} == {"林佳蓉", "王大明"}, "課 A 的兩筆都要在"
        assert {row["course_name"] for row in rows} == {"採血作業新進人員訓練"}, "不得混入其他課程"
        assert len(rows) == 2, "課 A 恰好兩筆——多一筆代表課程條件沒生效"

    async def test_只給關鍵字的行為與加入課程篩選前完全一致(self, client, db) -> None:
        """🔴 AC 2 的回歸護欄。

        #439 動到的是同一支查詢，而「以姓名跨課程查一個人」是這個功能**原本唯一**的
        用法。它一旦被改壞，畫面不會有任何異常——只是少幾列。此處釘死裁示 C 的預期集合。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"採血作業新進人員訓練", "成分製備標準作業教學"}

    async def test_兩者皆給時取交集(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "course_id": f["a"]}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert [row["user_name"] for row in rows] == ["林佳蓉"], "課 A 裡叫『林』的只有一位"

    async def test_課程篩選的總筆數也只算得到的那些(self, client, db) -> None:
        """與既有的「範圍判定進 WHERE」同一條理由：`meta.total` 必須與資料同源。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["a"]}, headers=_bearer(f["own"]))
        body = r.json()
        assert body["meta"]["total"] == len(body["data"]) == 2

    async def test_課程與結果篩選可疊加(self, client, db) -> None:
        """⭐ **用 `PASS` 而不是 `FAIL`，而且那不是隨便選的。**

        原本寫成「課 A + `FAIL`」，預期 `["王大明"]`。但 `t_own` 只 owner 課 A，而裁示 C
        讓他**本來就只看得到自己課的 `FAIL`**——所以少了課程條件、答案仍是 `["王大明"]`。
        這條（名字宣稱驗「疊加」的測試）在「拿掉課程條件」的變異下**照樣通過**，只驗到
        結果那一半。

        改用 `PASS` 後兩側都有鑑別力，判準是**各拿掉一個條件都會改變筆數**：

        | 情形 | 結果 |
        |---|---|
        | 課 A + `PASS` | 林佳蓉 1 筆 |
        | 少了課程條件 | 再加上林佳蓉在課 B 的 `PASS` → 2 筆 |
        | 少了結果條件 | 再加上王大明在課 A 的 `FAIL` → 2 筆 |

        ⚠️ 姓名的集合在第二種情形下**不會變**（同一個人在兩門課）——所以筆數那條斷言
        不可省，它才是撐住這條測試的那一個。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["a"], "result": APPROVAL_PASS}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert len(rows) == 1, "少了任一個條件都會多出一筆"
        assert rows[0]["user_name"] == "林佳蓉"
        assert rows[0]["course_name"] == "採血作業新進人員訓練"


class TestCourseFilterOwnership:
    """🔴 非管理者只能依**自己開設的課程**篩選（#439 實作時收斂，見 PR 說明）。

    #439 的「不構成傾印名冊」論證建立在「下拉只列自己的課」，但下拉是 UI。少了這道閘，
    教師可以用 `{course_id: 別人的課}` 一次撈出該課全部通過者的名單而不需要知道任何名字
    ——裁示 A 要擋的東西以課程為單位重演，而且會正常運作、不會有任何東西變紅。

    ⚠️ 一條測試只安排**一次**預期失敗的呼叫：失敗的請求會回滾整個 transaction，
    連前置資料一起沒掉，第二次呼叫會變成 401。
    """

    async def test_教師以他人課程篩選回403(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["b"]}, headers=_bearer(f["own"]))
        assert r.status_code == 403, r.text
        assert r.json()["error_code"] == "ET_APPROVAL_007"

    async def test_教師帶關鍵字也不能借他人課程篩選(self, client, db) -> None:
        """⚠️ 擋的是課程條件本身，不是「沒給關鍵字」——兩者是獨立的閘。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "course_id": f["b"]}, headers=_bearer(f["own"]))
        assert r.status_code == 403

    async def test_查無課程時對教師_fail_closed(self, client, db) -> None:
        """放行的話，不存在的 `course_id` 會退化成「沒有課程條件」的查詢。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": 99_999_999}, headers=_bearer(f["own"]))
        assert r.status_code == 403

    async def test_管理者可依任一課程篩選(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["c"]}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"捐血人健康評估標準教學"}

    async def test_管理者依他人課程篩選時可見範圍未被收窄(self, client, db) -> None:
        """🔴 AC 5 的替代斷言。

        原 AC 寫「教師選了他人課程時，不通過／已撤銷仍不可見」——但那條路徑現在是 403，
        斷言會落空。裁示 C 真正要守的是「分流未被本次改動影響」，在管理者這一側同樣
        驗得到：他選一門**他人**的課，仍應看得到不通過與撤銷原因（`true()` 未被課程
        條件擠掉）。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["d"]}, headers=_bearer(f["admin"]))
        rows = r.json()["data"]
        assert [row["is_revoked"] for row in rows] == [True]
        assert rows[0]["revoke_reason"] == "核可對象誤植"

    async def test_教師以自己課程篩選時分流未被收窄(self, client, db) -> None:
        """🔴 AC 5 的另一半：教師在**自己**的課裡仍看得到不通過。

        課程條件是 `AND` 疊加上去的，若有人誤把它寫成取代 `visible_clause`，本條會紅。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["a"], "keyword": "王大明"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["result"] for row in rows] == [APPROVAL_FAIL]


class TestFilterCourseOptions:
    """#439：課程下拉的選項來自**有核可紀錄的**課程，不是 ET01 的課程清單。"""

    async def test_教師只取得自己開設的課(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert [o["course_name"] for o in r.json()] == ["採血作業新進人員訓練"]

    async def test_管理者取得全部有核可紀錄的課(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert len(r.json()) == 4, "四門課各有核可紀錄"

    async def test_同一課程多筆核可只出現一次(self, client, db) -> None:
        """課 A 有兩筆核可（林佳蓉 / 王大明）——下拉不得出現兩個「採血作業新進人員訓練」。"""
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        options = r.json()
        assert len({o["course_id"] for o in options}) == len(options)

    async def test_沒有核可紀錄的課程不出現(self, client, db) -> None:
        """🔴 死選項的反面：下拉裡的每一項都必須選得出東西來。

        另一半理由是**已關閉課程**——核可紀錄絕大多數落在那些課上，而 ET01 的
        `scope=all` 恰好把它們排除。以核可紀錄為母體同時解掉這兩件事。
        """
        f = await _fixture(db)
        empty_course = await _course(db, owner=f["own"], name="尚無人核可的課")
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        assert empty_course not in {o["course_id"] for o in r.json()}

    async def test_下拉只有課程代碼與名稱(self, client, db) -> None:
        """這是下拉不是課程清單——多回欄位等於邀請前端拿它當 ET01 用。"""
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        assert set(r.json()[0]) == {"course_id", "course_name"}

    async def test_學員不可取得課程下拉(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["lin"]))
        assert r.status_code == 403
