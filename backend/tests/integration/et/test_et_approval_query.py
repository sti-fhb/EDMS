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
    """教師 ≡ 管理者：全部課程、全部結果（#548 裁示 1）。

    ## ⚠️ 本類別的斷言在 #548 **整組反轉**過，不是新寫的

    2026-09-21 的 SA Q1 裁示 C 曾要求教師依結果分流：「通過且未撤銷」看全部課程，
    「不通過 / 已撤銷」僅限自己 owner。#548 推翻了後半——原因不是分流做錯了，而是它
    **作為保密邊界站不住**：教師本來就能用姓名查到他人課程的通過紀錄，而課程篩選卻
    限制在自有課程，同一份資料兩條路兩種規則。

    保留下來的是**欄位**維度：`RESULT_NOTE` 與 `REVOKE_REASON` 仍限 owner + 管理者
    （裁示 2 / 7），見 `TestResultNoteRedaction` 與 `TestRevokeReasonRedaction`。

    ⛔ **不要把這些斷言「修正」回裁示 C。** 下面每一條的反面都曾經是正確的，而且有
    完整的理由；要再改回去是推翻 #548，不是修 bug。
    """

    async def test_教師查得他人課程的通過紀錄(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert "成分製備標準作業教學" in _names(r.json())

    async def test_教師查得到他人課程的不通過(self, client, db) -> None:
        """↔️ 裁示 C 時代這條是「查**不**到」。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert "捐血人健康評估標準教學" in _names(r.json())

    async def test_教師查得到他人課程已撤銷的通過(self, client, db) -> None:
        """↔️ 裁示 C 時代這條是「查**不**到」，且一併斷言撤銷原因不出現。

        現在紀錄本身看得到，但**原因文字仍遮蔽**——那一半沒有被推翻（裁示 7）。
        兩者分開驗：本條只管列在不在，原因的遮蔽由 `TestRevokeReasonRedaction` 管。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert "血品安全與品保概論" in _names(r.json())

    async def test_教師看得到自己課程的不通過(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "王大明"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["result"] for row in rows] == [APPROVAL_FAIL]

    async def test_教師視角的總筆數含全部四門課(self, client, db) -> None:
        """🔴 釘住「不再有任何範圍條件」，同時保留原本要守的「total 與 data 一致」。

        ↔️ 裁示 C 時代這條斷言的是 `total == 2`（看不到 C、D）。改成 4 之後它仍然守著
        原本的東西：若有人把範圍判定改成「取出後在 Python 過濾」，`meta.total` 會與
        `len(data)` 對不上——教師看到「共 4 筆」卻只翻得出 2 筆，且無任何錯誤訊息。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        body = r.json()
        assert body["meta"]["total"] == len(body["data"]) == 4

    async def test_教師與管理者查同一關鍵字得到相同的課程集合(self, client, db) -> None:
        """🔴 裁示 1 的核心斷言：兩種角色的可見範圍**完全相同**。

        ⚠️ 比對的是集合而非筆數——筆數相同但內容不同（各自看到對方看不到的那幾門）
        也會讓「相同」成立，而那正是分流時代的樣子。
        """
        f = await _fixture(db)
        as_teacher = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        as_admin = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))
        assert _names(as_teacher.json()) == _names(as_admin.json())
        assert len(_names(as_teacher.json())) == 4, "錨點：集合不得為空，否則兩邊皆空也會相等"


class TestResultAndRevokedFilter:
    """結果篩選 × 撤銷狀態——**兩個正交的維度**（#548 裁示 6）。

    ## 🔴 為何不是把 `REVOKED` 塞進 `result` 的值域

    `result` 對應 `ET_APPROVAL.RESULT`，`revoked` 對應 `IS_REVOKED`。一筆**被撤銷的
    紀錄其 `RESULT` 仍是 `PASS` 或 `FAIL`**——兩者從來不是同一個欄位的不同值。

    把它們塞進同一個參數，正是本 issue 要修的那個缺陷的成因：改制前「僅通過」的條件
    只有 `RESULT = 'PASS'`、完全沒有 `IS_REVOKED`，於是**選「僅通過」會列出已撤銷的列**。
    前端的單一下拉由呼叫端映射成參數對，介面維持四選一。

    | 下拉 | `result` | `revoked` |
    |---|---|---|
    | 全部結果 | `None` | `None` |
    | 僅通過 | `PASS` | `False` |
    | 僅不通過 | `FAIL` | `False` |
    | 僅已撤銷 | `None` | `True` |
    """

    async def test_僅通過不列出已撤銷的列(self, client, db) -> None:
        """🔴 這是改制前就已經錯的行為，不是本次新增的規則。

        撤銷只設 `IS_REVOKED`，`RESULT` 仍是 `PASS`；舊條件只比對 `RESULT`，於是課 D
        （已撤銷的通過）會出現在「僅通過」裡。
        """
        f = await _fixture(db)
        r = await client.post(
            _QUERY, json={"keyword": "林", "result": "PASS", "revoked": False}, headers=_bearer(f["own"])
        )
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"採血作業新進人員訓練", "成分製備標準作業教學"}
        assert "血品安全與品保概論" not in _names(r.json()), "已撤銷的通過不得出現在「僅通過」"

    async def test_僅不通過不列出已撤銷的列(self, client, db) -> None:
        """⚠️ `revoke` 不檢查 `RESULT`，所以**不通過的紀錄也撤銷得了**。

        既然「僅通過」排除已撤銷，「僅不通過」沒有理由不排除——不一致會變成下一個人
        要重新推理的東西。
        """
        f = await _fixture(db)
        e = await _course(db, owner=f["other"], name="輸血反應處置流程培訓")
        await _approval(
            db,
            course_id=e,
            user_id=f["lin"],
            result=APPROVAL_FAIL,
            approved_by=f["other"],
            revoked_by=f["admin"],
            revoke_reason="不通過也撤銷得了",
        )
        r = await client.post(
            _QUERY, json={"keyword": "林", "result": "FAIL", "revoked": False}, headers=_bearer(f["own"])
        )
        names = _names(r.json())
        assert "捐血人健康評估標準教學" in names, "未撤銷的不通過應列出（錨點）"
        assert "輸血反應處置流程培訓" not in names, "已撤銷的不通過不得出現在「僅不通過」"

    async def test_僅已撤銷只列出已撤銷的列(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "revoked": True}, headers=_bearer(f["own"]))
        body = r.json()
        assert _names(body) == {"血品安全與品保概論"}
        assert [row["is_revoked"] for row in body["data"]] == [True]

    async def test_全部結果含已撤銷的列(self, client, db) -> None:
        """裁示 6：預設視圖**不隱藏**已撤銷。

        隱藏會讓「查無」同時代表「從未核可」與「曾核可但被撤銷」，而那是方向最危險的
        假陰性——教師會讀成「這個人沒受過訓」。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert "血品安全與品保概論" in _names(r.json())

    async def test_篩選值不在值域時回422(self, client, db) -> None:
        """`result` 走 router 的值域驗證，不合法的值不該被當成「不篩」而放行全部。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "result": "WHATEVER"}, headers=_bearer(f["own"]))
        assert r.status_code == 422

    async def test_撤銷狀態不是_result_的值(self, client, db) -> None:
        """⛔ 釘住「兩個維度不可合併」：`REVOKED` 不得被接受為 `result` 的值。

        少了這條，日後有人「順手統一成一個參數」不會有東西變紅，而合併正是缺陷的成因。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "result": "REVOKED"}, headers=_bearer(f["own"]))
        assert r.status_code == 422


class TestResultNoteRedaction:
    """🔴 `RESULT_NOTE` 只對該課程 owner 與管理者顯示（2026-09-21 裁示，#548 裁示 2 維持）。

    裁示 C 原本只切**結果**維度，沒切**欄位**維度。而 `ApproveReq.result_note` 明文允許
    `PASS` 附備註——負面評語只要掛在通過上，就會隨「通過可查全部」流向全體教師。

    ⚠️ **#548 之後本類別守的範圍變大了。** 裁示 1 讓教師看得到他人課程的**不通過**與
    **已撤銷**，而那兩種列正是備註最可能寫負面文字的地方。改制前它們整列都不可見，
    欄位遮蔽從未在那條路徑上被驗過——`test_他人課程的不通過備註同樣遮蔽` 補的就是這個缺口。
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

    async def test_他人課程的不通過備註同樣遮蔽(self, client, db) -> None:
        """🔴 #548 新開的路徑：教師現在看得到他人課程的不通過，備註必須跟著被擋。

        課 C 是 `t_other` 的不通過，備註「實機操作需再加強」。改制前教師連這一列都
        看不到，所以遮蔽邏輯從未在「不通過」這條路徑上被驗證過。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "捐血人健康評估標準教學")
        assert row["result"] == APPROVAL_FAIL, "錨點：這一列確實是他人課程的不通過且看得到"
        assert row["result_note"] is None
        assert "實機操作需再加強" not in r.text

    async def test_學員端本來就不含備註欄位(self, client, db) -> None:
        """學員端是**結構性**不含（`MyApprovalRow` 沒這個欄位），不倚賴本次的遮蔽邏輯。"""
        f = await _fixture(db)
        r = await client.get(_MINE, headers=_bearer(f["lin"]))
        assert all("result_note" not in row for row in r.json()["data"])


class TestRevokeReasonRedaction:
    """🔴 `REVOKE_REASON` 只對該課程 owner 與管理者顯示（#548 裁示 7）。

    ## 這是本 issue 補掉的一道側門

    改制前 `revoke_reason` **從來沒有在 `_enrich` 被遮蔽過**——它是靠 `visible_clause`
    「已撤銷的列只有 owner 看得到」**間接**保護的。裁示 1 拿掉那個條件之後，撤銷原因
    就會對全體教師公開，而那與 `RESULT_NOTE` 是同一類東西：另一位教師對一個**具名的人**
    寫的負面自由文字（誤植、考核有問題）。

    ⚠️ 遮的只有**原因文字**。「已撤銷」這個事實、撤銷時間與撤銷人仍對全體教師可見
    ——否則教師會把一筆被撤銷的紀錄讀成有效的核可。
    """

    async def test_他人課程的撤銷原因對教師遮蔽(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血品安全與品保概論")
        assert row["is_revoked"] is True, "錨點：這一列確實是他人課程的已撤銷且看得到"
        assert row["revoke_reason"] is None
        assert "核可對象誤植" not in r.text, "原因不得以任何形式出現在回應中"

    async def test_撤銷的事實與時間人員仍對教師可見(self, client, db) -> None:
        """⚠️ 與上一條成對：遮的是原因文字，不是整個撤銷狀態。

        少了這條，把 `is_revoked` 一起遮掉也會讓上一條通過——而那會讓教師把已撤銷的
        紀錄讀成有效核可，方向比洩漏原因更糟。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血品安全與品保概論")
        assert row["is_revoked"] is True
        assert row["revoked_at"] is not None
        assert row["revoked_by_name"] == "李管理員"

    async def test_自己課程的撤銷原因照常顯示(self, client, db) -> None:
        """成對的正向錨點——少了它，整支查詢壞掉時遮蔽那條也會通過。"""
        f = await _fixture(db)
        e = await _course(db, owner=f["own"], name="血袋判讀實務")
        await _approval(
            db,
            course_id=e,
            user_id=f["lin"],
            result=APPROVAL_PASS,
            approved_by=f["own"],
            revoked_by=f["own"],
            revoke_reason="自己課程的撤銷原因",
        )
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血袋判讀實務")
        assert row["revoke_reason"] == "自己課程的撤銷原因"

    async def test_管理者看得到全部撤銷原因(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["admin"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "血品安全與品保概論")
        assert row["revoke_reason"] == "核可對象誤植"

    async def test_兩個欄位用同一個判斷(self, client, db) -> None:
        """⛔ 釘住「`result_note` 與 `revoke_reason` 不得各寫一份遮蔽條件」。

        各寫一份的話，日後有人改其中一個的條件（例如放寬給協同教師），另一個會靜默
        留在舊規則上，而兩者各自的測試都還會過。本條以**同一列同時帶兩個欄位**驗證
        兩者的遮蔽結果一致。
        """
        f = await _fixture(db)
        e = await _course(db, owner=f["other"], name="輸血反應處置流程培訓")
        await _approval(
            db,
            course_id=e,
            user_id=f["lin"],
            result=APPROVAL_PASS,
            approved_by=f["other"],
            revoked_by=f["admin"],
            revoke_reason="撤銷原因文字",
            note="考核備註文字",
        )
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))

        row = next(x for x in r.json()["data"] if x["course_name"] == "輸血反應處置流程培訓")
        assert (row["result_note"], row["revoke_reason"]) == (None, None), "同一列的兩個欄位必須同進同出"


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

    async def test_不給任何條件可查詢並回傳全部紀錄(self, client, db) -> None:
        """↔️ #548 裁示 3 之前，這條斷言的是 422 `ET_APPROVAL_006`（留白不可查全部）。

        ⚠️ 送 `json={}` 而非完全不帶 body——不帶 body 時 FastAPI 自己會先回 422
        （body 是必要參數），那條路徑根本到不了本規則。

        **為何放寬**：留白查詢是母體限制的最後一道，而裁示 1 與 4 已經把另外兩道拿掉。
        三道一起留著才有意義；只留這一道只會讓「用姓名逐個查」與「一次列出」在能力上
        相同、在操作上差很多，而畫面不會解釋為什麼。相對地，**讀取稽核成為必要**，
        見 `TestQueryAudit`。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["meta"]["total"] == 5, "fixture 共 5 筆核可紀錄，留白應全數取回"
        assert len(_names(body)) == 4

    async def test_關鍵字只有空白視同未給且照常查詢(self, client, db) -> None:
        """全空白仍須正規化為「未給」——否則比對會變成 `%%`（命中全部）而非「不篩」。

        ⚠️ 兩者今天的**結果**相同（都回全部），所以這條不能只比筆數。改以
        `normalize_search_criteria` 的回傳值在 unit 層釘住型別（`None` 而非 `""`），
        本條只確認 HTTP 層不會因為空白而變成 422 或 500。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "   "}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["total"] == 5

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
        #
        # ⚠️ 錨點刻意走**姓名**路徑（`林`）而非 Email：錨點必須獨立於被測的東西。
        # 初版用 `s_lin`（只經 Email local part 命中），於是變異掉 local part 比對時
        # 本組全部因**錨點失敗**而紅——紅的理由不是「網域又查得到了」，那樣的紅會讓人
        # 以為本組守住了它其實沒守的事。
        baseline = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
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

    「只給課程」這條路徑的正確性同時取決於兩件只有真 DB 看得出來的事：`course_id`
    條件真的下推到 `WHERE`、以及 `paginate()` 的 `meta.total` 與資料用的是同一個 `stmt`。
    純函式那層（`test_approval_query_rules.py`）擋不住其中任何一件。

    > ↔️ 原本還有第三件「`visible_clause` 仍與它 `AND` 相接」——該條件已於 #548 退役。
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

    async def test_只給關鍵字時跨課程取回該學員的全部紀錄(self, client, db) -> None:
        """🔴 AC 2 的回歸護欄：「以姓名跨課程查一個人」是這個功能**原本唯一**的用法。

        它一旦被改壞，畫面不會有任何異常——只是少幾列。所以此處釘死完整的預期集合，
        而不是只斷言「有幾筆」。

        ↔️ #548 之前這裡釘的是裁示 C 的 2 門課（教師看不到他人課程的不通過與已撤銷）；
        裁示 1 統一可見範圍後，同一個查詢應取回林佳蓉的**全部 4 門**。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林"}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {
            "採血作業新進人員訓練",
            "成分製備標準作業教學",
            "捐血人健康評估標準教學",
            "血品安全與品保概論",
        }

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


class TestCourseFilterAnyCourse:
    """課程篩選不分 owner（#548 裁示 4）。

    ## ↔️ 本類別整組反轉過

    #439 曾要求非管理者只能依自己開設的課程篩選（403 `ET_APPROVAL_007`），理由是
    「少了這道閘，教師可以用 `{course_id: 別人的課}` 一次撈出該課全部通過者的名單」。

    #548 裁示 4 拿掉它：那道閘擋的是**取得成本**而非**可見資料**——教師本來就能用
    姓名查到他人課程的紀錄。同一份資料在「用姓名查」與「用課程篩」兩條路上有兩種規則，
    而畫面從不解釋為什麼。⚠️ 代價是「不指名整批取回」變成一鍵可達，由讀取稽核承接
    （裁示 5，見 `TestQueryAudit`）。

    ⛔ 要把擁有權閘加回來就是推翻 #548，不是修漏洞。
    """

    async def test_教師可依他人課程篩選(self, client, db) -> None:
        """↔️ 原本是 403 `ET_APPROVAL_007`。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["b"]}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"成分製備標準作業教學"}

    async def test_教師帶關鍵字也可依他人課程篩選(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"keyword": "林", "course_id": f["b"]}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"成分製備標準作業教學"}

    async def test_查無課程時回空清單而非錯誤(self, client, db) -> None:
        """↔️ 原本對教師 fail-closed（403）。

        擁有權閘拿掉後，不存在的 `course_id` 就只是一個篩不到東西的條件。
        ⛔ **不可回 404**——那會讓本端點變成一支課程存在性的 oracle（`course_id`
        直接來自使用者、未經任何篩選）。回空清單是刻意的。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": 99_999_999}, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["total"] == 0

    async def test_管理者可依任一課程篩選(self, client, db) -> None:
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["c"]}, headers=_bearer(f["admin"]))
        assert r.status_code == 200, r.text
        assert _names(r.json()) == {"捐血人健康評估標準教學"}

    async def test_以他人課程篩選時撤銷原因仍遮蔽(self, client, db) -> None:
        """🔴 裁示 4 **不得連帶鬆掉裁示 7**。

        課程篩選開放之後，教師可以直接指定他人的課；若欄位遮蔽只在「跨課程查詢」那條
        路徑上生效，這裡就會漏。兩個維度是獨立的——列的進出不再受限，欄位仍受限。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["d"]}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["is_revoked"] for row in rows] == [True], "錨點：教師確實看得到這一列"
        assert rows[0]["revoke_reason"] is None
        assert "核可對象誤植" not in r.text

    async def test_管理者依他人課程篩選看得到撤銷原因(self, client, db) -> None:
        """與上一條成對的正向錨點。"""
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["d"]}, headers=_bearer(f["admin"]))
        rows = r.json()["data"]
        assert [row["is_revoked"] for row in rows] == [True]
        assert rows[0]["revoke_reason"] == "核可對象誤植"

    async def test_以課程篩選時仍看得到該課的不通過(self, client, db) -> None:
        """🔴 AC 5 的另一半：課程條件是**疊加**的，不是取代其他條件。

        ↔️ 原名「分流未被收窄」——當時守的是「課程條件不得取代 `visible_clause`」。
        分流已於 #548 退役，但「疊加而非取代」這件事仍要守：若有人把 `course_id`
        寫成取代 `result` / `revoked` 的條件，本條不會紅，但 `test_課程與結果篩選可疊加`
        會紅——兩條一起才完整。
        """
        f = await _fixture(db)
        r = await client.post(_QUERY, json={"course_id": f["a"], "keyword": "王大明"}, headers=_bearer(f["own"]))
        rows = r.json()["data"]
        assert [row["result"] for row in rows] == [APPROVAL_FAIL]


class TestFilterCourseOptions:
    """課程下拉的選項來自**有核可紀錄的**課程，不是 ET01 的課程清單（#439）。

    ⚠️ **母體不分 owner**（#548 裁示 4）——下拉與 `search` 的擁有權閘是一組的，
    那道閘拿掉之後，下拉再限自己的課只會讓「選得到的」少於「查得到的」。
    """

    async def test_教師取得全部有核可紀錄的課(self, client, db) -> None:
        """↔️ 原本斷言教師只拿得到自己開設的那一門。"""
        f = await _fixture(db)
        r = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        assert r.status_code == 200, r.text
        assert len(r.json()) == 4, "四門課各有核可紀錄，不分 owner"

    async def test_教師與管理者的下拉內容相同(self, client, db) -> None:
        """🔴 與 `TestTeacherScope::test_教師與管理者查同一關鍵字得到相同的課程集合` 成對。

        下拉決定「選得到什麼」、查詢決定「查得到什麼」——兩者的範圍必須一致，否則會
        出現「這門課查得到卻選不到」這種無法解釋的狀態。
        """
        f = await _fixture(db)
        as_teacher = await client.get(_FILTER_COURSES, headers=_bearer(f["own"]))
        as_admin = await client.get(_FILTER_COURSES, headers=_bearer(f["admin"]))
        assert {o["course_id"] for o in as_teacher.json()} == {o["course_id"] for o in as_admin.json()}
        assert len(as_teacher.json()) == 4, "錨點：兩邊皆空也會相等"

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
