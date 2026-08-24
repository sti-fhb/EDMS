"""ET02 章節編排整合測試（US3 / #202）。

重點在需要真 DB 才驗得了的三件事：`SORT_ORDER` 的追加與遞補、樂觀鎖粒度
（課程 / 章節各自 VERSION），以及**刪除章節時學員紀錄之連帶硬刪**。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import ITEM_MATERIAL, ROLE_TEACHER
from app.et.course.models import EtChapter, EtItem, EtMaterial
from app.et.progress.models import EtProgress
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


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


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _course_with_chapters(client, db, uid: str, names: list[str]) -> tuple[int, list[int]]:
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    ids = []
    for name in names:
        r = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": name}, headers=_bearer(uid))
        assert r.status_code == 201, r.text
        ids.append(r.json()["chapter_id"])
    return cid, ids


class TestAppend:
    async def test_追加至最末且順序自_1_起(self, client, db) -> None:
        uid = await _user(db, "ETH_A1")
        _, ids = await _course_with_chapters(client, db, uid, ["第一章", "第二章", "第三章"])
        rows = await db.scalars(select(EtChapter).where(EtChapter.chapter_id.in_(ids)).order_by(EtChapter.sort_order))
        assert [c.sort_order for c in rows] == [1, 2, 3]

    async def test_章節名全空白被擋(self, client, db) -> None:
        uid = await _user(db, "ETH_A2")
        created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
        r = await client.post(
            f"{_COURSES}/{created.json()['course_id']}/chapters",
            json={"chapter_name": "  "},
            headers=_bearer(uid),
        )
        assert r.status_code == 422


class TestReorder:
    async def test_完整陣列重排(self, client, db) -> None:
        uid = await _user(db, "ETH_R1")
        cid, ids = await _course_with_chapters(client, db, uid, ["A", "B", "C"])
        detail = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        version = detail.json()["version"]

        r = await client.put(
            f"{_COURSES}/{cid}/chapters/order",
            json={"chapter_ids": [ids[2], ids[0], ids[1]], "version": version},
            headers=_bearer(uid),
        )
        assert r.status_code == 204
        after = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        assert [c["chapter_id"] for c in after.json()["chapters"]] == [ids[2], ids[0], ids[1]]

    async def test_缺漏章節之重排被擋(self, client, db) -> None:
        uid = await _user(db, "ETH_R2")
        cid, ids = await _course_with_chapters(client, db, uid, ["A", "B"])
        detail = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        r = await client.put(
            f"{_COURSES}/{cid}/chapters/order",
            json={"chapter_ids": [ids[0]], "version": detail.json()["version"]},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_CHAPTER_002"

    async def test_重排以課程層版本保護(self, client, db) -> None:
        uid = await _user(db, "ETH_R3")
        cid, ids = await _course_with_chapters(client, db, uid, ["A", "B"])
        r = await client.put(
            f"{_COURSES}/{cid}/chapters/order",
            json={"chapter_ids": ids, "version": 999},
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_重排不遞增章節版本(self, client, db) -> None:
        """FR-ET-US3-15：不同實體並行編輯互不衝突。

        若重排順手遞增各章節 `VERSION`，另一裝置正在改章節名的請求會無故 409。
        """
        uid = await _user(db, "ETH_R4")
        cid, ids = await _course_with_chapters(client, db, uid, ["A", "B"])
        detail = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        chapter_versions_before = {c["chapter_id"]: c["version"] for c in detail.json()["chapters"]}

        await client.put(
            f"{_COURSES}/{cid}/chapters/order",
            json={"chapter_ids": [ids[1], ids[0]], "version": detail.json()["version"]},
            headers=_bearer(uid),
        )
        after = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        assert {c["chapter_id"]: c["version"] for c in after.json()["chapters"]} == chapter_versions_before


class TestRename:
    async def test_更名並遞增章節版本(self, client, db) -> None:
        uid = await _user(db, "ETH_N1")
        cid, ids = await _course_with_chapters(client, db, uid, ["舊名"])
        r = await client.put(
            f"/api/et/chapters/{ids[0]}", json={"chapter_name": "新名", "version": 0}, headers=_bearer(uid)
        )
        assert r.status_code == 204
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == ids[0]))
        await db.refresh(chapter)
        assert chapter.chapter_name == "新名" and chapter.version == 1

    async def test_改章節不影響課程版本(self, client, db) -> None:
        """課程 / 章節各自維護 VERSION（AC 31）。"""
        uid = await _user(db, "ETH_N2")
        cid, ids = await _course_with_chapters(client, db, uid, ["章"])
        before = (await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))).json()["version"]
        await client.put(f"/api/et/chapters/{ids[0]}", json={"chapter_name": "改", "version": 0}, headers=_bearer(uid))
        after = (await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))).json()["version"]
        assert after == before

    async def test_查無章節回_404(self, client, db) -> None:
        uid = await _user(db, "ETH_N3")
        r = await client.put(
            "/api/et/chapters/99999999", json={"chapter_name": "X", "version": 0}, headers=_bearer(uid)
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_CHAPTER_001"


class TestDeleteChapter:
    async def test_軟刪除本體並遞補後續順序(self, client, db) -> None:
        uid = await _user(db, "ETH_D1")
        cid, ids = await _course_with_chapters(client, db, uid, ["A", "B", "C"])
        r = await client.delete(f"/api/et/chapters/{ids[0]}", headers=_bearer(uid))
        assert r.status_code == 204

        deleted = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == ids[0]))
        await db.refresh(deleted)
        assert deleted.deleted == 1, "章節本體為軟刪除"

        after = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        remaining = after.json()["chapters"]
        assert [c["chapter_id"] for c in remaining] == [ids[1], ids[2]]
        assert [c["sort_order"] for c in remaining] == [1, 2], "後續章節順序自動往前遞補"

    async def test_連帶軟刪項目並硬刪學員進度(self, client, db) -> None:
        """data-model §ET_CHAPTER：項目軟刪、**學員紀錄硬刪**（與專案預設相反之刻意例外）。

        本 issue 尚無建立項目之端點（屬 #203），故以 ORM 直接建測資——空表刪除永遠會過，
        不建測資等於沒測到這條規則。
        """
        uid = await _user(db, "ETH_D2")
        _, ids = await _course_with_chapters(client, db, uid, ["有內容的章節"])
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == ids[0]))
        now = utcnow()

        material = EtMaterial(material_name="教材", created_user=uid, created_date=now)
        db.add(material)
        await db.flush()
        item = EtItem(
            chapter_id=chapter.chapter_id,
            item_type=ITEM_MATERIAL,
            sort_order=1,
            material_id=material.material_id,
            version=0,
            created_user=uid,
            created_date=now,
        )
        db.add(item)
        await db.flush()
        db.add(
            EtProgress(
                user_id="STUDENT_X",
                course_id=chapter.course_id,
                item_id=item.item_id,
                is_completed=True,
                created_user="STUDENT_X",
                created_date=now,
            )
        )
        await db.flush()

        r = await client.delete(f"/api/et/chapters/{ids[0]}", headers=_bearer(uid))
        assert r.status_code == 204

        await db.refresh(item)
        assert item.deleted == 1, "項目為軟刪除（連動）"
        remaining_progress = await db.scalar(select(EtProgress).where(EtProgress.item_id == item.item_id))
        assert remaining_progress is None, "學員進度須 hard delete，不得留下孤兒紀錄"

    async def test_他人不可刪章節(self, client, db) -> None:
        owner = await _user(db, "ETH_D3")
        other = await _user(db, "ETH_D4")
        _, ids = await _course_with_chapters(client, db, owner, ["章"])
        r = await client.delete(f"/api/et/chapters/{ids[0]}", headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"
