"""DM 文件廢止之後，ET 兩端的實際行為（ET-14 / #341 T120 / AC 5）。

## 盤點查到的兩個缺口

AC 5 有兩個半句，各自對應一個當時無人覆蓋的接縫：

**教師端阻擋發布**：`tests/unit/et/test_publish_rules.py` 驗的是 `BLOCK_OBSOLETE_DOC` 的組合邏輯，
餵的是**造假的 `obsolete_doc_ids=frozenset({...})`**。真正去問 DM 的是
`publish_service._obsolete_doc_ids()`，而 `test_et_publish.py` 17 條裡**沒有一條碰 `OBSOLETE_DOC`**。

**學員端顯示廢止標籤**：`test_et_material.py::test_已廢止文件顯示廢止標記` 打的是**教師端**
`GET /materials/{mid}`。學員端是 `GET /materials/{id}/content`——另一支查詢、另一個 schema，
`test_et_learning.py` 16 條**無一驗它**。

兩者都是「兩端各自有測試、中間那段沒有」的形狀——與 `test_dm_kpi_download_seam.py` 同型。
差別在這裡的中間段是**跨模組**的：`app/services` → `DmDocumentService` → DM 的真實 `status`。

## 為什麼 unit 補不上

`evaluate_publish(snapshot, obsolete_doc_ids=...)` 是純函式，餵什麼就算什麼。若
`_obsolete_doc_ids()` 哪天漏看 `OBSOLETE`、或跨模組出口的欄位改名，unit 全綠、
`test_et_publish.py` 全綠，而教師會成功發布一門指向已廢止 SOP 的課——那正是這項
檢核存在的唯一理由。
"""

import os

import pytest

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory  # noqa: F401  # 使 FK 目標表進入 metadata
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocument, DmDocVersion
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.common.dm_client import TRAINING_CATEGORY
from app.et.constants import ITEM_MATERIAL, ROLE_STUDENT, ROLE_TEACHER, SOURCE_INVITATION_CODE
from app.et.course.publish_rules import BLOCK_OBSOLETE_DOC
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


async def _user(db, user_id: str, role: str = ROLE_TEACHER) -> str:
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


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _dm_doc(db, doc_id: str, *, status: str = "PUBLISHED") -> None:
    """建一份 DM 文件 + 一個發布版，並回填 `current_version_id`。"""
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=f"文件{doc_id}",
            category_code=TRAINING_CATEGORY,
            func_code=None,
            current_version_id=None,
            status=status,
            created_user="ed",
            created_date=now,
        )
    )
    await db.flush()
    version = DmDocVersion(
        doc_id=doc_id,
        version_no="v1.0",
        change_summary="摘要",
        file_name="a.pdf",
        file_path=os.path.join(storage_root(), doc_id, "v1.0.pdf"),
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        approver_user_id="appr",
        published_date=now,
        created_user="ed",
        created_date=now,
    )
    db.add(version)
    await db.flush()
    doc = await db.get(DmDocument, doc_id)
    doc.current_version_id = version.version_id
    await db.flush()


async def _obsolete(db, doc_id: str) -> None:
    """把一份**已被引用**的文件廢止——模擬 DM 端在課程建好之後才廢止。"""
    doc = await db.get(DmDocument, doc_id)
    doc.status = "OBSOLETE"
    await db.flush()


async def _course_with_doc(client, db, uid: str, *, doc_id: str) -> tuple[int, int]:
    """建一門**其餘檢核全部滿足**的課程，其教材引用 `doc_id`。回 `(course_id, material_id)`。

    「其餘全部滿足」是刻意的：這樣 `publish-check` 若回 `can_publish=False`，唯一可能的
    原因就是廢止文件那一項，不會與其他缺漏混淆。
    """
    created = await client.post(
        _COURSES,
        json={
            "course_name": "引用文件的課程",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2026-12-31T00:00:00Z",
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    tag = EtTag(
        tag_name=f"標籤{course_id}",
        is_active=True,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    db.add(EtCourseTag(course_id=course_id, tag_id=tag.tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid)
    )
    item = await client.post(
        f"/api/et/chapters/{chapter.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(uid),
    )
    material_id = item.json()["material_id"]

    attached = await client.put(
        f"/api/et/materials/{material_id}",
        json={
            "material_name": "教材",
            "description_html": None,
            "doc_ids": [doc_id],
            "video_ids": [],
            "version": 0,
        },
        headers=_bearer(uid),
    )
    assert attached.status_code == 204, attached.text
    return course_id, material_id


async def _check(client, uid: str, course_id: int) -> dict:
    r = await client.get(f"{_COURSES}/{course_id}/publish-check", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    return r.json()


class TestPublishBlockedByObsoleteDoc:
    """AC 5 前半句：教師端阻擋發布。驗的是 ET → DM 那段橋，不是純函式的組合邏輯。"""

    async def test_引用文件被廢止後檢核轉為不可發布(self, client, db) -> None:
        """同一門課、同一份文件，只改 DM 端的 `status`——前後對照才證明是廢止造成的。

        分開寫成「廢止的課不可發布」會漏掉一種壞法：若 `_obsolete_doc_ids()` 恆回全部
        `doc_id`，那條測試照樣綠，而所有引用文件的課程都會發不出去。
        """
        uid = await _user(db, "t_obs01")
        doc_id = "DM-TRAINING-000901"
        await _dm_doc(db, doc_id)
        course_id, _ = await _course_with_doc(client, db, uid, doc_id=doc_id)

        before = await _check(client, uid, course_id)
        assert before["can_publish"] is True, f"基準課程應可發布，實得 blockers={before['blockers']}"

        await _obsolete(db, doc_id)

        after = await _check(client, uid, course_id)
        assert after["can_publish"] is False
        codes = [b["code"] for b in after["blockers"]]
        assert codes == [BLOCK_OBSOLETE_DOC], f"唯一缺漏應為廢止文件，實得 {after['blockers']}"

    async def test_發布請求被擋且課程仍為草稿(self, client, db) -> None:
        """`publish-check` 只是預檢；真正的守門在 `publish` 本身。

        兩者各自呼叫 `_evaluate`，若只有預檢擋而 `publish` 沒擋，前端繞過預檢直打即可
        發布一門指向廢止 SOP 的課。
        """
        uid = await _user(db, "t_obs02")
        doc_id = "DM-TRAINING-000902"
        await _dm_doc(db, doc_id)
        course_id, _ = await _course_with_doc(client, db, uid, doc_id=doc_id)
        await _obsolete(db, doc_id)

        r = await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(uid))

        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error_code"] == "ET_PUBLISH_001"
        assert BLOCK_OBSOLETE_DOC in [b["code"] for b in body["blockers"]]

    async def test_廢止待簽核不阻擋發布(self, client, db) -> None:
        """`PENDING_OBSOLETE` 期間文件仍屬有效，不可提前阻擋。

        與上一條互為邊界：只驗「廢止會擋」而不驗「待簽核不擋」，把判定寫成
        `status != 'PUBLISHED'` 也會全綠，卻會在簽核期間讓所有相關課程發不出去。
        """
        uid = await _user(db, "t_obs03")
        doc_id = "DM-TRAINING-000903"
        await _dm_doc(db, doc_id)
        course_id, _ = await _course_with_doc(client, db, uid, doc_id=doc_id)

        doc = await db.get(DmDocument, doc_id)
        doc.status = "PENDING_OBSOLETE"
        await db.flush()

        assert (await _check(client, uid, course_id))["can_publish"] is True


class TestStudentSeesObsoleteFlag:
    """AC 5 後半句：學員端顯示廢止標籤。打的是 `/content`，與教師端是不同支查詢。"""

    async def _enrolled_student(self, client, db, uid: str, course_id: int, student_id: str) -> str:
        await _user(db, student_id, role=ROLE_STUDENT)
        db.add(
            EtEnrollment(
                course_id=course_id,
                user_id=student_id,
                join_source=SOURCE_INVITATION_CODE,
                joined_at=utcnow(),
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user=student_id,
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        return student_id

    async def test_學員端顯示廢止旗標且仍讀得到內容(self, client, db) -> None:
        """AC 17：廢止**不等於**下架。標籤要出現，但文件本身仍可閱讀廢止前最後一版。

        兩件事必須同時成立——只驗 `obsolete is True` 而不驗 `available`，把廢止實作成
        「整列不回傳」也會綠，而那會讓學員在讀到一半的課程裡看到內容突然消失。
        """
        uid = await _user(db, "t_obs04")
        doc_id = "DM-TRAINING-000904"
        await _dm_doc(db, doc_id)
        course_id, material_id = await _course_with_doc(client, db, uid, doc_id=doc_id)
        await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(uid))
        student = await self._enrolled_student(client, db, uid, course_id, "s_obs04")

        before = await client.get(f"/api/et/materials/{material_id}/content", headers=_bearer(student))
        assert before.status_code == 200, before.text
        assert before.json()["docs"][0]["obsolete"] is False

        await _obsolete(db, doc_id)

        after = await client.get(f"/api/et/materials/{material_id}/content", headers=_bearer(student))
        assert after.status_code == 200, after.text
        row = after.json()["docs"][0]
        assert row["obsolete"] is True, "學員端未顯示廢止旗標（教師端有、學員端沒有，就是這條在守的缺口）"
        assert row["available"] is True, "廢止不等於下架——仍須讀得到廢止前最後一版"
        assert row["doc_id"] == doc_id and row["version_id"] is not None

    async def test_廢止待簽核對學員不顯示為廢止(self, client, db) -> None:
        """與教師端 `test_廢止待簽核不視為廢止` 對稱。兩端對同一狀態必須給同一個答案。"""
        uid = await _user(db, "t_obs05")
        doc_id = "DM-TRAINING-000905"
        await _dm_doc(db, doc_id, status="PENDING_OBSOLETE")
        course_id, material_id = await _course_with_doc(client, db, uid, doc_id=doc_id)
        await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(uid))
        student = await self._enrolled_student(client, db, uid, course_id, "s_obs05")

        r = await client.get(f"/api/et/materials/{material_id}/content", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["docs"][0]["obsolete"] is False

    async def test_已發布課程之文件被廢止不影響學員取檔授權(self, client, db) -> None:
        """廢止後學員仍能取得教材頁；驗的是 ET 端不會因 DM 狀態而誤擋整個教材。

        ET 對「取不到的文件」的設計是 `available=False` 而非讓整頁失敗（見
        `learning/service.py` 的 `_doc_row`）。廢止不屬於取不到，故整頁與該列都應正常。
        """
        uid = await _user(db, "t_obs06")
        doc_id = "DM-TRAINING-000906"
        await _dm_doc(db, doc_id)
        course_id, material_id = await _course_with_doc(client, db, uid, doc_id=doc_id)
        await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(uid))
        student = await self._enrolled_student(client, db, uid, course_id, "s_obs06")
        await _obsolete(db, doc_id)

        r = await client.get(f"/api/et/materials/{material_id}/content", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert len(r.json()["docs"]) == 1, "廢止文件不得從教材清單中消失"


async def test_廢止不影響已發布課程的既有引用(client, db) -> None:
    """發布之後才廢止，課程狀態不變——阻擋只發生在發布那一刻。

    `ET_MATERIAL_DOC` 只存 `DOC_ID`，故引用恆指向當前版；若有人把廢止檢核誤加到讀取
    路徑上，已上線課程會在 DM 端廢止的瞬間集體失效。
    """
    uid = await _user(db, "t_obs07")
    doc_id = "DM-TRAINING-000907"
    await _dm_doc(db, doc_id)
    course_id, _ = await _course_with_doc(client, db, uid, doc_id=doc_id)
    published = await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(uid))
    assert published.status_code == 200, published.text

    await _obsolete(db, doc_id)

    detail = await client.get(f"{_COURSES}/{course_id}", headers=_bearer(uid))
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "PUBLISHED", "既有發布狀態不因文件事後廢止而改變"
