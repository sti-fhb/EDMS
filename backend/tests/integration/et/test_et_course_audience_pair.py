"""課程端受訓對象配對（#538）：寫入、驗證、只增不減、補邀請、ET01 篩選。

帶入規則本身（哪些人會被帶入）在 `test_et_tag_invite.py`；本檔驗課程 API 這一層。
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import TAG_TYPE_UNIT, EtTag
from app.et.constants import COURSE_PUBLISHED, ROLE_STUDENT, ROLE_TEACHER
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
        await _publish_directly(db, cid)
        late_nurse = await _user(db, "s_cp07a")  # 發布後才掛上舊配對——不屬於這條路徑
        new_clerk = await _user(db, "s_cp07b")
        await pair_user(db, late_nurse, nurse, tsgh)
        await pair_user(db, new_clerk, clerk, tsgh)

        r = await _put_audiences(client, teacher, cid, [old_pair, _pair(tsgh, clerk)])

        assert r.status_code == 204, r.text
        enrolled = set(
            await db.scalars(
                select(EtEnrollment.user_id).where(EtEnrollment.course_id == cid, EtEnrollment.deleted == 0)
            )
        )
        assert enrolled == {new_clerk}


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
