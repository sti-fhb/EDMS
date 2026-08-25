"""ET02 課程 CRUD 與授權整合測試（US3 / #202）。

只驗需要真 DB 的「接線」——標籤啟用狀態查詢、樂觀鎖 rowcount、擁有權判定串到端點、
稽核寫入。純集合／字串規則已於 `tests/unit/et/test_course_rules.py` 覆蓋，此處不重複。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtTag
from app.et.constants import COURSE_PUBLISHED, ROLE_STUDENT, ROLE_TEACHER
from app.et.course.models import EtCourse
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_URL = "/api/et/courses"


async def _user(db, user_id: str, *, roles: tuple[str, ...] = (ROLE_TEACHER,)) -> str:
    """建立可通過平台認證且具指定 ET 角色之帳號。"""
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


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _tag_ids(db, limit: int = 2) -> list[int]:
    """取啟用中之種子標籤 ID（migration 種了 5 筆；不寫死 ID，避免 identity 起始值假設）。"""
    rows = await db.scalars(
        select(EtTag.tag_id).where(EtTag.deleted == 0, EtTag.is_active.is_(True)).order_by(EtTag.tag_id).limit(limit)
    )
    return list(rows)


class TestCreateDraft:
    async def test_僅填名稱即可存草稿(self, client, db) -> None:
        """AC：受訓單位標籤與起訖時間於草稿允許留空（發布時才檢核，屬 #204）。"""
        uid = await _user(db, "ETC_C1")
        r = await client.post(_URL, json={"course_name": "採血作業訓練"}, headers=_bearer(uid))
        assert r.status_code == 201, r.text
        course_id = r.json()["course_id"]

        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
        assert course.status == "DRAFT"
        assert course.owner_id == uid, "OWNER_ID 須取自 JWT，不由請求帶入"
        assert course.open_start_at is None and course.open_end_at is None
        assert course.require_approval is False, "REQUIRE_APPROVAL 預設否"

    async def test_owner_id_不可由請求覆寫(self, client, db) -> None:
        """防越權：即使請求塞 owner_id，仍以 JWT 為準（多餘欄位由 Pydantic 忽略）。"""
        uid = await _user(db, "ETC_C2")
        r = await client.post(_URL, json={"course_name": "課程", "owner_id": "SOMEONE_ELSE"}, headers=_bearer(uid))
        assert r.status_code == 201
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == r.json()["course_id"]))
        assert course.owner_id == uid

    async def test_僅教師可建立課程(self, client, db) -> None:
        """SA 裁示 Q2：不具教師角色者被 ET 存取閘之角色檢核擋下。"""
        uid = await _user(db, "ETC_C3", roles=(ROLE_STUDENT,))
        r = await client.post(_URL, json={"course_name": "課程"}, headers=_bearer(uid))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"

    async def test_名稱全空白被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_C4")
        r = await client.post(_URL, json={"course_name": "   "}, headers=_bearer(uid))
        assert r.status_code == 422

    async def test_描述超過_500_字被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_C5")
        r = await client.post(_URL, json={"course_name": "課程", "description": "字" * 501}, headers=_bearer(uid))
        assert r.status_code == 422

    async def test_起訖時間一律以_aware_datetime_儲存(self, client, db) -> None:
        """`OPEN_START_AT` / `OPEN_END_AT` 為 TIMESTAMPTZ；naive 值會被 PostgreSQL
        以連線時區解讀而靜默位移，使 #204「起始時間前學員不可見」與 #16 到期自動關閉
        算錯。schema 之 `_ensure_aware` 對 naive 補 UTC——此處驗兩種輸入皆落為同一時刻。
        """
        uid = await _user(db, "ETC_C7")
        # 前端正常送帶時區之 ISO 8601；此處另送 naive 值模擬其他客戶端
        r = await client.post(
            _URL,
            json={
                "course_name": "課程",
                "open_start_at": "2026-04-15T09:00:00Z",
                "open_end_at": "2026-07-31T17:00",
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 201
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == r.json()["course_id"]))
        assert course.open_start_at.tzinfo is not None
        assert course.open_end_at.tzinfo is not None
        assert course.open_start_at.hour == 9, "帶 Z 之輸入不應被再次位移"
        assert course.open_end_at.hour == 17, "naive 輸入應視為 UTC，不得依連線時區位移"

    async def test_掛停用標籤被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_C6")
        now = utcnow()
        db.add(
            EtTag(
                tag_name="已停用單位",
                is_active=False,
                is_all=False,
                is_builtin=False,
                display_order=99,
                created_user="t",
                created_date=now,
            )
        )
        await db.flush()
        disabled = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == "已停用單位"))
        r = await client.post(_URL, json={"course_name": "課程", "tag_ids": [disabled]}, headers=_bearer(uid))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_COURSE_004"


class TestCreateWithChapters:
    """建立課程時一併帶入章節——使新增流程不必「先存草稿才能加章節」。"""

    async def test_一次建立課程與章節且順序依陣列(self, client, db) -> None:
        uid = await _user(db, "ETC_H1")
        r = await client.post(
            _URL,
            json={"course_name": "課程", "chapters": ["第一章", "第二章", "第三章"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 201
        detail = await client.get(f"{_URL}/{r.json()['course_id']}", headers=_bearer(uid))
        chapters = detail.json()["chapters"]
        assert [c["chapter_name"] for c in chapters] == ["第一章", "第二章", "第三章"]
        assert [c["sort_order"] for c in chapters] == [1, 2, 3]

    async def test_空白章節名被擋且課程不會被建出來(self, client, db) -> None:
        """同一交易內建立——章節驗證失敗時不應留下沒有章節的孤兒課程。"""
        uid = await _user(db, "ETC_H2")
        r = await client.post(
            _URL, json={"course_name": "不該存在的課程", "chapters": ["正常", "  "]}, headers=_bearer(uid)
        )
        assert r.status_code == 422
        orphan = await db.scalar(select(EtCourse).where(EtCourse.course_name == "不該存在的課程"))
        assert orphan is None, "驗證失敗時不得留下課程"

    async def test_更新端點不接受_chapters(self, client, db) -> None:
        """課程建立後章節由專屬端點維護；更新請求帶 chapters 應被忽略而非誤建。"""
        uid = await _user(db, "ETC_H3")
        created = await client.post(_URL, json={"course_name": "課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        r = await client.put(
            f"{_URL}/{cid}",
            json={"course_name": "課程", "version": 0, "chapters": ["偷渡章節"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 204
        detail = await client.get(f"{_URL}/{cid}", headers=_bearer(uid))
        assert detail.json()["chapters"] == [], "更新端點不應建立章節"


class TestCapabilities:
    """操作能力（比照 DM `Capabilities`）——回「能力」而非「角色」，使授權判斷只有一個來源。"""

    async def test_教師可建立課程(self, client, db) -> None:
        uid = await _user(db, "ETC_P1")
        r = await client.get(f"{_URL}/capabilities", headers=_bearer(uid))
        assert r.status_code == 200
        assert r.json()["can_create_course"] is True

    async def test_僅學員者不可建立課程(self, client, db) -> None:
        uid = await _user(db, "ETC_P2", roles=(ROLE_STUDENT,))
        r = await client.get(f"{_URL}/capabilities", headers=_bearer(uid))
        assert r.status_code == 200
        assert r.json()["can_create_course"] is False, "學員不應看到「新增課程」入口"

    async def test_capabilities_不被動態路由吃掉(self, client, db) -> None:
        """`/courses/{course_id}` 之 course_id 為 int；路由順序錯誤時本路徑會回 422。"""
        uid = await _user(db, "ETC_P3")
        r = await client.get(f"{_URL}/capabilities", headers=_bearer(uid))
        assert r.status_code == 200, "capabilities 須宣告於動態路由之前"


class TestTimeWindow:
    async def test_迄止早於起始被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_W1")
        r = await client.post(
            _URL,
            json={
                "course_name": "課程",
                "open_start_at": "2026-07-31T17:00:00Z",
                "open_end_at": "2026-04-15T09:00:00Z",
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_起訖相同被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_W2")
        same = "2026-04-15T09:00:00Z"
        r = await client.post(
            _URL,
            json={"course_name": "課程", "open_start_at": same, "open_end_at": same},
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_已發布課程沿用過去之起始時間仍可儲存(self, client, db) -> None:
        """SA 裁示：「起始 ≥ 當下」只對使用者**改動**的值成立。

        若後端無條件檢核，已開課課程（起始必然在過去）之後就永遠存不了檔——
        而 AC 28 明訂已發布課程可繼續編輯。
        """
        uid = await _user(db, "ETC_W3")
        created = await client.post(
            _URL,
            json={
                "course_name": "課程",
                "open_start_at": "2020-01-01T00:00:00Z",
                "open_end_at": "2030-01-01T00:00:00Z",
            },
            headers=_bearer(uid),
        )
        assert created.status_code == 201
        cid = created.json()["course_id"]
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_PUBLISHED
        await db.flush()

        r = await client.put(
            f"{_URL}/{cid}",
            json={
                "course_name": "改名",
                "open_start_at": "2020-01-01T00:00:00Z",
                "open_end_at": "2030-01-01T00:00:00Z",
                "version": course.version,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204


class TestInputBounds:
    """輸入界限（Security Review，#202）。

    這些界限的價值不在擋住惡意使用者，而在**讓越界回 4xx 而非未處理的 500**——
    500 代表例外逃出應用層，既是放大攻擊面，也讓真正的錯誤被雜訊淹沒。
    比照 #185 `assign` 之 `_MAX_GROUPS` / `_MAX_BIGINT` 前例。
    """

    async def test_超大_course_id_回_422_而非_500(self, client, db) -> None:
        """路徑參數超出 BIGINT 時，asyncpg 比對會溢位；未設界限會成為未處理的 500。"""
        uid = await _user(db, "ETC_B1")
        r = await client.get(f"{_URL}/99999999999999999999999", headers=_bearer(uid))
        assert r.status_code == 422

    async def test_超長_tag_ids_被擋(self, client, db) -> None:
        """數萬筆的 `IN (...)` 會讓 SQLAlchemy / asyncpg 拋未處理例外。"""
        uid = await _user(db, "ETC_B2")
        r = await client.post(
            _URL, json={"course_name": "課程", "tag_ids": list(range(1, 50001))}, headers=_bearer(uid)
        )
        assert r.status_code == 422

    async def test_非正數_tag_id_被擋(self, client, db) -> None:
        """`TAG_ID` 為 Identity 正整數；負數 / 零屬不合法輸入。"""
        uid = await _user(db, "ETC_B3")
        r = await client.post(_URL, json={"course_name": "課程", "tag_ids": [-1]}, headers=_bearer(uid))
        assert r.status_code == 422

    async def test_超長_chapter_ids_被擋(self, client, db) -> None:
        uid = await _user(db, "ETC_B4")
        created = await client.post(_URL, json={"course_name": "課程"}, headers=_bearer(uid))
        r = await client.put(
            f"{_URL}/{created.json()['course_id']}/chapters/order",
            json={"chapter_ids": list(range(1, 50001)), "version": 0},
            headers=_bearer(uid),
        )
        assert r.status_code == 422


class TestReadAndOwnership:
    async def test_擁有者取得詳細_is_owner_為真(self, client, db) -> None:
        uid = await _user(db, "ETC_R1")
        created = await client.post(_URL, json={"course_name": "我的課"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        r = await client.get(f"{_URL}/{cid}", headers=_bearer(uid))
        assert r.status_code == 200
        body = r.json()
        assert body["is_owner"] is True
        assert body["owner_name"] == "測試ETC_R1", "owner_name 取自 DP_USER 唯讀 join"

    async def test_他人可閱覽但_is_owner_為假(self, client, db) -> None:
        """spec.md §擁有權判定：他人課程僅可閱覽，不是 403。"""
        owner = await _user(db, "ETC_R2")
        other = await _user(db, "ETC_R3")
        created = await client.post(_URL, json={"course_name": "他的課"}, headers=_bearer(owner))
        cid = created.json()["course_id"]
        r = await client.get(f"{_URL}/{cid}", headers=_bearer(other))
        assert r.status_code == 200
        assert r.json()["is_owner"] is False

    async def test_他人不可編輯(self, client, db) -> None:
        owner = await _user(db, "ETC_R4")
        other = await _user(db, "ETC_R5")
        created = await client.post(_URL, json={"course_name": "他的課"}, headers=_bearer(owner))
        cid, ver = created.json()["course_id"], created.json()["version"]
        r = await client.put(f"{_URL}/{cid}", json={"course_name": "改名", "version": ver}, headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_學員不可讀取課程詳細(self, client, db) -> None:
        """ET02 為教師畫面。若只掛 ET 存取閘，人人皆有學員角色 → 任何登入者都能讀到
        他人**草稿**課程，違反 spec_us3 AC 8「儲存草稿⋯⋯學員端不顯示」。
        學員端之課程讀取有自己的可見性規則（PUBLISHED 且 now >= OPEN_START_AT），
        屬 ET Issue #4 / #5 之端點。
        """
        owner = await _user(db, "ETC_R7")
        student = await _user(db, "ETC_R8", roles=(ROLE_STUDENT,))
        created = await client.post(_URL, json={"course_name": "草稿課"}, headers=_bearer(owner))
        r = await client.get(f"{_URL}/{created.json()['course_id']}", headers=_bearer(student))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_AUTH_001"

    async def test_學員不可取得標籤下拉(self, client, db) -> None:
        student = await _user(db, "ETC_R9", roles=(ROLE_STUDENT,))
        r = await client.get("/api/et/tags", headers=_bearer(student))
        assert r.status_code == 403

    async def test_查無課程回_404(self, client, db) -> None:
        uid = await _user(db, "ETC_R6")
        r = await client.get(f"{_URL}/99999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_COURSE_001"


class TestUpdateAndTags:
    async def test_草稿可自由增刪標籤(self, client, db) -> None:
        uid = await _user(db, "ETC_U1")
        tags = await _tag_ids(db, 2)
        created = await client.post(_URL, json={"course_name": "課程", "tag_ids": tags}, headers=_bearer(uid))
        cid, ver = created.json()["course_id"], created.json()["version"]

        # 移除一個、換成另一個
        r = await client.put(
            f"{_URL}/{cid}",
            json={"course_name": "課程", "tag_ids": [tags[1]], "version": ver},
            headers=_bearer(uid),
        )
        assert r.status_code == 204
        detail = await client.get(f"{_URL}/{cid}", headers=_bearer(uid))
        assert detail.json()["tag_ids"] == [tags[1]]

    async def test_已發布不可移除既有標籤(self, client, db) -> None:
        uid = await _user(db, "ETC_U2")
        tags = await _tag_ids(db, 2)
        created = await client.post(_URL, json={"course_name": "課程", "tag_ids": tags}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_PUBLISHED  # 發布屬 #204，此處直接改狀態以驗保護規則
        await db.flush()

        r = await client.put(
            f"{_URL}/{cid}",
            json={"course_name": "課程", "tag_ids": [tags[0]], "version": course.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_COURSE_003"

    async def test_已發布可新增標籤(self, client, db) -> None:
        uid = await _user(db, "ETC_U3")
        tags = await _tag_ids(db, 2)
        created = await client.post(_URL, json={"course_name": "課程", "tag_ids": [tags[0]]}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_PUBLISHED
        await db.flush()

        r = await client.put(
            f"{_URL}/{cid}",
            json={"course_name": "課程", "tag_ids": tags, "version": course.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 204

    async def test_require_approval_已發布仍可調整(self, client, db) -> None:
        """FR-ET-US3-16：草稿 / 已發布 / 已關閉任一狀態皆可調整。"""
        uid = await _user(db, "ETC_U4")
        created = await client.post(_URL, json={"course_name": "課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_PUBLISHED
        await db.flush()

        r = await client.put(
            f"{_URL}/{cid}",
            json={"course_name": "課程", "require_approval": True, "version": course.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 204
        await db.refresh(course)
        assert course.require_approval is True

    async def test_版本不符回_409(self, client, db) -> None:
        uid = await _user(db, "ETC_U5")
        created = await client.post(_URL, json={"course_name": "課程"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        r = await client.put(f"{_URL}/{cid}", json={"course_name": "改名", "version": 999}, headers=_bearer(uid))
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"


class TestDeleteDraft:
    async def test_擁有者可刪草稿(self, client, db) -> None:
        uid = await _user(db, "ETC_D1")
        created = await client.post(_URL, json={"course_name": "草稿課"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        r = await client.delete(f"{_URL}/{cid}", headers=_bearer(uid))
        assert r.status_code == 204
        assert (await client.get(f"{_URL}/{cid}", headers=_bearer(uid))).status_code == 404

    async def test_已發布不可刪(self, client, db) -> None:
        """SA 裁示 Q1：已發布改用 US11 之關閉。"""
        uid = await _user(db, "ETC_D2")
        created = await client.post(_URL, json={"course_name": "已發布課"}, headers=_bearer(uid))
        cid = created.json()["course_id"]
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_PUBLISHED
        await db.flush()

        r = await client.delete(f"{_URL}/{cid}", headers=_bearer(uid))
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_COURSE_005"

    async def test_他人不可刪(self, client, db) -> None:
        owner = await _user(db, "ETC_D3")
        other = await _user(db, "ETC_D4")
        created = await client.post(_URL, json={"course_name": "課"}, headers=_bearer(owner))
        r = await client.delete(f"{_URL}/{created.json()['course_id']}", headers=_bearer(other))
        assert r.status_code == 403


class TestTagOptions:
    async def test_下拉排除停用標籤(self, client, db) -> None:
        uid = await _user(db, "ETC_T1")
        now = utcnow()
        db.add(
            EtTag(
                tag_name="停用單位A",
                is_active=False,
                is_all=False,
                is_builtin=False,
                display_order=98,
                created_user="t",
                created_date=now,
            )
        )
        await db.flush()
        r = await client.get("/api/et/tags", headers=_bearer(uid))
        assert r.status_code == 200
        assert "停用單位A" not in [t["tag_name"] for t in r.json()]

    async def test_帶_course_id_時保留該課程既有已掛之停用標籤(self, client, db) -> None:
        """FR-ET-US3-03：停用標籤排除於可選清單，但課程既有已掛者保留、不受影響。"""
        uid = await _user(db, "ETC_T2")
        tags = await _tag_ids(db, 1)
        created = await client.post(_URL, json={"course_name": "課程", "tag_ids": tags}, headers=_bearer(uid))
        cid = created.json()["course_id"]

        # 掛上後才把該標籤停用——模擬管理者事後停用
        tag = await db.scalar(select(EtTag).where(EtTag.tag_id == tags[0]))
        tag.is_active = False
        await db.flush()

        r = await client.get(f"/api/et/tags?course_id={cid}", headers=_bearer(uid))
        returned = {t["tag_id"]: t["is_active"] for t in r.json()}
        assert tags[0] in returned, "既有已掛之停用標籤仍須回傳，否則前端顯示不出該 chip"
        assert returned[tags[0]] is False

        r_plain = await client.get("/api/et/tags", headers=_bearer(uid))
        assert tags[0] not in [t["tag_id"] for t in r_plain.json()], "不帶 course_id 時不應出現"
