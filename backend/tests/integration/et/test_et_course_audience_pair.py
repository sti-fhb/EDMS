"""課程端受訓對象配對（#538）：寫入、驗證、只增不減、補邀請、ET01 篩選。

帶入規則本身（哪些人會被帶入）在 `test_et_tag_invite.py`；本檔驗課程 API 這一層。
"""

import pytest
from sqlalchemy import func, select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import TAG_TYPE_UNIT, EtCourseTag, EtTag
from app.et.constants import COURSE_CLOSED, COURSE_PUBLISHED, ITEM_MATERIAL, ROLE_STUDENT, ROLE_TEACHER
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole
from tests.integration.et._tag_pairs import all_roles_id, all_units_id, new_tag, pair_user, tag_id

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_SONGSHAN = "國防醫學院三軍總醫院松山分院"
_TSGH = "國防醫學院三軍總醫院"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT) -> str:
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


def _pair(unit_id: int, role_id: int) -> dict:
    return {"unit_tag_id": unit_id, "tag_id": role_id}


async def _create(client, teacher: str, audiences: list[dict], name: str = "配對課程") -> int:
    r = await client.post(
        _COURSES,
        json={
            "course_name": name,
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2027-09-30T00:00:00Z",
            "audiences": audiences,
        },
        headers=_bearer(teacher),
    )
    assert r.status_code == 201, r.text
    return r.json()["course_id"]


async def _detail(client, teacher: str, cid: int) -> dict:
    r = await client.get(f"{_COURSES}/{cid}", headers=_bearer(teacher))
    assert r.status_code == 200, r.text
    return r.json()


async def _put_audiences(client, teacher: str, cid: int, audiences: list[dict]):
    body = await _detail(client, teacher, cid)
    return await client.put(
        f"{_COURSES}/{cid}",
        json={
            "course_name": body["course_name"],
            "description": body["description"],
            "open_start_at": body["open_start_at"],
            "open_end_at": body["open_end_at"],
            "require_approval": body["require_approval"],
            "audiences": audiences,
            "version": body["version"],
        },
        headers=_bearer(teacher),
    )


async def _add_minimal_content(client, teacher: str, cid: int) -> None:
    """補一章一教材，讓這門課過得了發布檢核。

    ⚠️ #720 之後才需要：受訓對象的帶入與邀請信移到「更新」（`content/apply`），而更新
    會重跑發布六項檢核。本檔其餘案例不打更新，故**只有需要驗帶入的那條**要備內容。

    ⛔ 必須在 `_publish_directly` **之前**呼叫：課程一旦是已發布，新增章節就走暫存區，
    這份內容會在這裡變成「本次編輯新增的東西」而混進被驗的那批差異裡。
    """
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text


async def _publish_directly(db, cid: int) -> None:
    """直接改狀態為已發布——本檔驗的是「已發布之後的配對編輯」，不是發布流程本身。"""
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == cid)
        # 邀請碼全表唯一，以 course_id 推導避免同一測試內多門課撞鍵
        .values(status=COURSE_PUBLISHED, invitation_code=f"{cid % 100_000_000:08d}")
    )
    await db.flush()


class TestWriteAndRead:
    async def test_配對寫入後讀回且帶顯示文字(self, client, db) -> None:
        teacher = await _user(db, "t_cp01", ROLE_TEACHER)
        all_units, everyone = await all_units_id(db), await all_roles_id(db)
        nurse, clerk = await tag_id(db, "護理師"), await tag_id(db, "行政人員")
        songshan = await tag_id(db, _SONGSHAN)
        cid = await _create(
            client, teacher, [_pair(all_units, nurse), _pair(songshan, clerk), _pair(all_units, everyone)]
        )

        got = {(a["unit_tag_id"], a["tag_id"]): a["label"] for a in (await _detail(client, teacher, cid))["audiences"]}

        assert got == {
            (all_units, nurse): "護理師",  # 全單位省略
            (songshan, clerk): f"{_SONGSHAN} + 行政人員",
            (all_units, everyone): "全體",  # 兩個都是通用值
        }

    async def test_重複的配對被擋下(self, client, db) -> None:
        teacher = await _user(db, "t_cp02", ROLE_TEACHER)
        p = _pair(await all_units_id(db), await tag_id(db, "護理師"))

        r = await client.post(_COURSES, json={"course_name": "x", "audiences": [p, p]}, headers=_bearer(teacher))

        assert r.status_code == 422, r.text


class TestValidation:
    """新配對的兩欄類型必須正確且為啟用中（422 `ET_COURSE_004`）。"""

    @pytest.mark.parametrize("swap", ["單位欄放職位", "職位欄放單位"])
    async def test_欄位錯置被擋下(self, client, db, swap) -> None:
        """單位欄只接受單位、職位欄只接受職位——錯置的配對在匹配時永遠不成立，靜默存進去
        只會讓教師以為設好了。"""
        teacher = await _user(db, "t_cp03", ROLE_TEACHER)
        nurse, tsgh = await tag_id(db, "護理師"), await tag_id(db, _TSGH)
        pair = _pair(nurse, nurse) if swap == "單位欄放職位" else _pair(tsgh, tsgh)

        r = await client.post(_COURSES, json={"course_name": "x", "audiences": [pair]}, headers=_bearer(teacher))

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_COURSE_004"

    async def test_停用的單位不可新掛(self, client, db) -> None:
        teacher = await _user(db, "t_cp04", ROLE_TEACHER)
        retired = await new_tag(db, "已裁撤單位_cp04", tag_type=TAG_TYPE_UNIT, is_active=False)

        r = await client.post(
            _COURSES,
            json={"course_name": "x", "audiences": [_pair(retired, await tag_id(db, "護理師"))]},
            headers=_bearer(teacher),
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_COURSE_004"

    async def test_既有配對中的停用單位不影響存檔(self, client, db) -> None:
        """FR-ET-US3-03 延續到單位：已掛的停用標籤保留——否則標籤一停用，那門課再也存不了檔。"""
        teacher = await _user(db, "t_cp05", ROLE_TEACHER)
        unit = await new_tag(db, "將裁撤單位_cp05", tag_type=TAG_TYPE_UNIT)
        pair = _pair(unit, await tag_id(db, "護理師"))
        cid = await _create(client, teacher, [pair])
        await db.execute(update(EtTag).where(EtTag.tag_id == unit).values(is_active=False))
        await db.flush()

        r = await _put_audiences(client, teacher, cid, [pair])

        assert r.status_code == 204, r.text


class TestPublishedCourse:
    """FR-ET-US3-02：已發布課程只增不減，新增時只對**新配對**的人補邀請。"""

    async def test_同職位換單位視為移除_被擋下(self, client, db) -> None:
        teacher = await _user(db, "t_cp06", ROLE_TEACHER)
        nurse = await tag_id(db, "護理師")
        cid = await _create(client, teacher, [_pair(await all_units_id(db), nurse)])
        await _publish_directly(db, cid)

        r = await _put_audiences(client, teacher, cid, [_pair(await tag_id(db, _TSGH), nurse)])

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_COURSE_003"

    async def test_新增配對只補邀請新配對的人(self, client, db) -> None:
        teacher = await _user(db, "t_cp07", ROLE_TEACHER)
        nurse, clerk, tsgh = await tag_id(db, "護理師"), await tag_id(db, "行政人員"), await tag_id(db, _TSGH)
        old_pair = _pair(tsgh, nurse)
        cid = await _create(client, teacher, [old_pair])
        await _add_minimal_content(client, teacher, cid)
        await _publish_directly(db, cid)
        late_nurse = await _user(db, "s_cp07a")  # 發布後才掛上舊配對——不屬於這條路徑
        new_clerk = await _user(db, "s_cp07b")
        await pair_user(db, late_nurse, nurse, tsgh)
        await pair_user(db, new_clerk, clerk, tsgh)

        r = await _put_audiences(client, teacher, cid, [old_pair, _pair(tsgh, clerk)])

        assert r.status_code == 204, r.text
        # ⚠️ #720：已發布課程的受訓對象改走暫存，帶入與寄信落在按「更新」那一刻。
        # 在 `PUT` 當下帶入是帶入一件還沒發生的事（教師可以接著按「取消」）。
        applied = await client.post(f"/api/et/courses/{cid}/content/apply", headers=_bearer(teacher))
        assert applied.status_code == 200, applied.text

        enrolled = set(
            await db.scalars(
                select(EtEnrollment.user_id).where(EtEnrollment.course_id == cid, EtEnrollment.deleted == 0)
            )
        )
        assert enrolled == {new_clerk}


class TestRemovedPairAddedBack:
    """🔴 移除過的配對再加回來，不得撞唯一鍵（#720 code review HIGH）。

    `UQ_ET_COURSE_TAG_COURSE_TAG` 建在 `(COURSE_ID, TAG_ID, UNIT_TAG_ID)` 上、**不含
    `DELETED`**，所以軟刪的那一列仍然佔著那個鍵。草稿路徑早就處理了（`apply` 的
    docstring 明寫「以重新啟用既有軟刪除列而非插入新列處理 add」），暫存路徑於 #720
    才開始寫這張表，漏了同一道 → 直接 INSERT 會 `IntegrityError` → **500**。

    ⚠️ 這條驗的是**整個往返**（移除 → 更新 → 加回 → 更新），不是只驗 `_revive_soft_deleted`
    這支函式——函式單獨正確但沒有被 `_write` 呼叫到的話，單測照樣綠。
    """

    async def test_已關閉課程移除配對再加回不會_500(self, client, db) -> None:
        teacher = await _user(db, "t_rb01", ROLE_TEACHER)
        nurse, clerk, tsgh = await tag_id(db, "護理師"), await tag_id(db, "行政人員"), await tag_id(db, _TSGH)
        keep, removed = _pair(tsgh, nurse), _pair(tsgh, clerk)
        cid = await _create(client, teacher, [keep, removed])
        await _add_minimal_content(client, teacher, cid)
        await _publish_directly(db, cid)
        # 已關閉課程才可移除既有配對（#586）
        await db.execute(update(EtCourse).where(EtCourse.course_id == cid).values(status=COURSE_CLOSED))
        await db.flush()

        # ① 移除一組並生效 → 活表留下 DELETED=1 的那一列
        assert (await _put_audiences(client, teacher, cid, [keep])).status_code == 204
        applied = await client.post(f"/api/et/courses/{cid}/content/apply", headers=_bearer(teacher))
        assert applied.status_code == 200, applied.text

        # ② 再把同一組加回來並生效——這裡原本會撞唯一鍵
        assert (await _put_audiences(client, teacher, cid, [keep, removed])).status_code == 204
        again = await client.post(f"/api/et/courses/{cid}/content/apply", headers=_bearer(teacher))

        assert again.status_code == 200, f"移除過的配對加回來不得 500：{again.text}"
        pairs = set(
            await db.execute(
                select(EtCourseTag.unit_tag_id, EtCourseTag.tag_id).where(
                    EtCourseTag.course_id == cid, EtCourseTag.deleted == 0
                )
            )
        )
        assert pairs == {(tsgh, nurse), (tsgh, clerk)}
        # 🔴 復活而非新增：同一組配對反覆增刪不得累積出一堆軟刪列（與草稿路徑同一行為）
        total = await db.scalar(select(func.count()).select_from(EtCourseTag).where(EtCourseTag.course_id == cid))
        assert total == 2, f"應復活既有列而非插入新列，實際共 {total} 列"


class TestListFilter:
    """#538 SA Q2 裁示：ET01 篩選改為「單位」「職位」兩欄，**只看字面**。"""

    async def _three_courses(self, client, db, slug: str) -> dict[str, int]:
        teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
        all_units, everyone = await all_units_id(db), await all_roles_id(db)
        nurse, clerk = await tag_id(db, "護理師"), await tag_id(db, "行政人員")
        songshan = await tag_id(db, _SONGSHAN)
        ids = {
            "全單位護理師": await _create(client, teacher, [_pair(all_units, nurse)], f"{slug}-A"),
            "松山護理師": await _create(client, teacher, [_pair(songshan, nurse)], f"{slug}-B"),
            "松山全體": await _create(client, teacher, [_pair(songshan, everyone)], f"{slug}-C"),
            # 單位與職位分別出現在**不同組**配對：松山+行政、全單位+護理師
            "拆開的組合": await _create(
                client, teacher, [_pair(songshan, clerk), _pair(all_units, nurse)], f"{slug}-D"
            ),
        }
        for cid in ids.values():
            await _publish_directly(db, cid)
        return ids | {"_teacher": teacher}  # type: ignore[return-value]

    async def _names(self, client, teacher: str, slug: str, **params) -> set[str]:
        r = await client.get(_COURSES, params={"scope": "all", "q": slug, **params}, headers=_bearer(teacher))
        assert r.status_code == 200, r.text
        return {c["course_name"].split("-")[1] for c in r.json()["data"]}

    async def test_職位篩選不展開全體(self, client, db) -> None:
        ids = await self._three_courses(client, db, "cpf1")
        names = await self._names(client, ids["_teacher"], "cpf1", tag_id=await tag_id(db, "護理師"))
        assert names == {"A", "B", "D"}, "選「護理師」不得列出 (松山分院, 全體)"

    async def test_單位篩選不展開全單位(self, client, db) -> None:
        ids = await self._three_courses(client, db, "cpf2")
        names = await self._names(client, ids["_teacher"], "cpf2", unit_tag_id=await tag_id(db, _SONGSHAN))
        assert names == {"B", "C", "D"}, "選「松山分院」不得列出 (全單位, 護理師)"

    async def test_兩欄並用須同一組配對同時符合(self, client, db) -> None:
        ids = await self._three_courses(client, db, "cpf3")
        names = await self._names(
            client, ids["_teacher"], "cpf3", unit_tag_id=await tag_id(db, _SONGSHAN), tag_id=await tag_id(db, "護理師")
        )
        assert names == {"B"}, "D 的松山與護理師分屬兩組配對，不得列出"

    async def test_篩選下拉含兩類並標示類型(self, client, db) -> None:
        teacher = await _user(db, "t_cpf4", ROLE_TEACHER)
        r = await client.get(f"{_COURSES}/filter-tags", headers=_bearer(teacher))
        types = {t["tag_name"]: t["tag_type"] for t in r.json()}
        assert types["護理師"] == "AUDIENCE"
        assert types[_SONGSHAN] == "UNIT"
