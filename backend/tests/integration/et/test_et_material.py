"""ET02 教材內容整合測試（US3 / #203）。

重點在需要真 DB／真 DM 資料才驗得了的事：

1. 說明文字之**後端消毒**確實寫進 DB（繞過前端直打 API 也擋得住）
2. 「至少擇一媒材」在三類媒材的各種組合下之判定
3. DM 文件引用——恆取最新版、廢止標記、`PENDING_OBSOLETE` 不阻擋
4. **刪除引用後可再次引用同一份文件**（部分唯一索引之修正；原全表唯一會永久卡住）
"""

import os

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory  # 測試 fixture：建 DM 側測資並使 FK 目標表進入 metadata
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocument, DmDocVersion
from app.dp.users.models import DpUser
from app.et.common.dm_client import TRAINING_CATEGORY
from app.et.constants import ITEM_MATERIAL, ROLE_TEACHER
from app.et.material.models import EtMaterial, EtMaterialDoc
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


async def _material(client, uid: str) -> int:
    """建課程 → 章節 → 教材項目，回 `material_id`。"""
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(uid),
    )
    return item.json()["material_id"]


async def _dm_doc(db, doc_id: str, *, name="訓練文件", status="PUBLISHED", category=TRAINING_CATEGORY) -> None:
    """建一份 DM 文件（含發布版）。`status` 可為 PUBLISHED / PENDING_OBSOLETE / OBSOLETE。

    非 `TRAINING` 分類需先建 `DM_CATEGORY`——只有 `TRAINING` 由 migration seed。
    """
    now = utcnow()
    if category != TRAINING_CATEGORY:
        exists = await db.scalar(select(DmCategory).where(DmCategory.category_code == category))
        if exists is None:
            db.add(
                DmCategory(
                    category_code=category, category_name=f"測試{category}", created_user="seed", created_date=now
                )
            )
            await db.flush()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=name,
            category_code=category,
            func_code=None,
            current_version_id=None,
            status=status,
            created_user="ed",
            created_date=now,
        )
    )
    await db.flush()
    ver = DmDocVersion(
        doc_id=doc_id,
        version_no="v1.0",
        change_summary="摘要",
        file_name="a.pdf",
        file_path=os.path.join(storage_root(), doc_id, "v1.0.pdf"),
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=now,
        created_user="ed",
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id))
    doc.current_version_id = ver.version_id
    await db.flush()


async def _put(client, uid: str, mid: int, **overrides):
    """送**完整**教材狀態（名稱 + 說明 + 文件集合 + 保留的影片）。

    全量覆寫契約：未列出的既有引用 / 影片會被刪除（2026-08-26 依實測回饋改）。
    """
    payload = {
        "material_name": "教材",
        "description_html": None,
        "doc_ids": [],
        "video_ids": [],
        "version": 0,
        **overrides,
    }
    return await client.put(f"/api/et/materials/{mid}", json=payload, headers=_bearer(uid))


class TestGetDetail:
    async def test_空殼教材可讀取(self, client, db) -> None:
        """剛建立的空殼三類媒材皆空——這是合法狀態（檢核在儲存時才套用）。"""
        uid = await _user(db, "ETM_G1")
        mid = await _material(client, uid)
        r = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["material_name"] == "教材"
        assert body["description_html"] is None
        assert body["videos"] == [] and body["docs"] == []

    async def test_查無教材回_404(self, client, db) -> None:
        uid = await _user(db, "ETM_G2")
        r = await client.get("/api/et/materials/999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_MATERIAL_001"

    async def test_非擁有者不可讀取(self, client, db) -> None:
        owner = await _user(db, "ETM_G3")
        other = await _user(db, "ETM_G4")
        mid = await _material(client, owner)
        r = await client.get(f"/api/et/materials/{mid}", headers=_bearer(other))
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestUpdate:
    async def test_說明文字存檔後可讀回(self, client, db) -> None:
        uid = await _user(db, "ETM_U1")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, material_name="教材改名", description_html="<p>說明</p>")
        assert r.status_code == 204, r.text
        material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == mid))
        assert (material.material_name, material.description_html, material.version) == ("教材改名", "<p>說明</p>", 1)

    async def test_腳本於後端被消毒後才落地(self, client, db) -> None:
        """繞過前端直打 API 的情境——這是後端消毒存在的理由（#188 B1）。"""
        uid = await _user(db, "ETM_U2")
        mid = await _material(client, uid)
        await _put(client, uid, mid, description_html='<p onclick="steal()">正常內容</p><script>alert(1)</script>')
        material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == mid))
        assert "script" not in material.description_html.lower()
        assert "onclick" not in material.description_html.lower()
        assert "正常內容" in material.description_html

    async def test_三類媒材皆空被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_U3")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid)
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_002"

    async def test_說明文字全是腳本等同空白被擋(self, client, db) -> None:
        """先消毒再檢核——順序顛倒會放行一個看似有說明、實則空白的教材。"""
        uid = await _user(db, "ETM_U4")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, description_html="<script>alert(1)</script>")
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_002"

    async def test_只有文件引用時可存空說明(self, client, db) -> None:
        uid = await _user(db, "ETM_U5")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000101")
        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-000101"])
        assert r.status_code == 204, r.text

    async def test_版本不符回_409(self, client, db) -> None:
        uid = await _user(db, "ETM_U6")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, description_html="<p>x</p>", version=99)
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_名稱全空白被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_U7")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, material_name="  ", description_html="<p>x</p>")
        assert r.status_code == 422

    async def test_超長說明文字被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_U8")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, description_html="<p>" + "x" * 60_000 + "</p>")
        assert r.status_code == 422


class TestDocReference:
    async def test_新增引用後可於詳細讀到_dm_即時資料(self, client, db) -> None:
        uid = await _user(db, "ETM_D1")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000201", name="安全守則")
        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-000201"])
        assert r.status_code == 204, r.text

        doc = (await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))).json()["docs"][0]
        assert (doc["doc_id"], doc["doc_name"], doc["version_no"]) == ("DM-TRAINING-000201", "安全守則", "v1.0")
        assert doc["obsolete"] is False and doc["unavailable"] is False

    async def test_恆取_dm_最新版無快取延遲(self, client, db) -> None:
        """ET 只存 DOC_ID，DM 發布新版後 ET 這邊應自動反映。"""
        uid = await _user(db, "ETM_D2")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000202")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000202"])

        now = utcnow()
        v2 = DmDocVersion(
            doc_id="DM-TRAINING-000202",
            version_no="v2.0",
            change_summary="改版",
            file_name="b.pdf",
            file_path=os.path.join(storage_root(), "DM-TRAINING-000202", "v2.0.pdf"),
            file_size=200,
            file_mime="application/pdf",
            status="PUBLISHED",
            published_date=now,
            created_user="ed",
            created_date=now,
        )
        db.add(v2)
        await db.flush()
        doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-TRAINING-000202"))
        doc.current_version_id = v2.version_id
        await db.flush()

        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert detail.json()["docs"][0]["version_no"] == "v2.0"

    async def test_已廢止文件顯示廢止標記(self, client, db) -> None:
        uid = await _user(db, "ETM_D3")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000203")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000203"])
        doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-TRAINING-000203"))
        doc.status = "OBSOLETE"
        await db.flush()

        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert detail.json()["docs"][0]["obsolete"] is True

    async def test_既有廢止引用不阻擋後續存檔(self, client, db) -> None:
        """只驗新增的文件——否則「只是改個教材名稱」會因某份舊文件被廢止而存不了。"""
        uid = await _user(db, "ETM_D3B")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000213")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000213"])
        doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-TRAINING-000213"))
        doc.status = "OBSOLETE"
        await db.flush()

        r = await _put(client, uid, mid, material_name="改個名字", doc_ids=["DM-TRAINING-000213"], version=1)
        assert r.status_code == 204, r.text

    async def test_廢止待簽核不視為廢止(self, client, db) -> None:
        uid = await _user(db, "ETM_D4")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000204", status="PENDING_OBSOLETE")
        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-000204"])
        assert r.status_code == 204, r.text
        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert detail.json()["docs"][0]["obsolete"] is False

    async def test_同一次請求重複帶同一份文件被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_D5")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000205")
        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-000205", "DM-TRAINING-000205"])
        assert r.status_code == 422

    async def test_移除引用後可再次引用同一份文件(self, client, db) -> None:
        """⚠️ 這條釘住 #185 建表缺陷之修正。

        原 `(MATERIAL_ID, DOC_ID)` 為**全表**唯一約束，已軟刪除的列仍佔住該組合——
        教師誤刪一份引用後將**永久**無法加回。改為部分唯一索引後才成立。
        """
        uid = await _user(db, "ETM_D6")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000206")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000206"])
        await _put(client, uid, mid, description_html="<p>說明</p>", doc_ids=[], version=1)
        again = await _put(client, uid, mid, description_html="<p>說明</p>", doc_ids=["DM-TRAINING-000206"], version=2)
        assert again.status_code == 204, "移除後應可再次引用同一份文件"

        rows = list(await db.scalars(select(EtMaterialDoc).where(EtMaterialDoc.material_id == mid)))
        assert [r.deleted for r in sorted(rows, key=lambda r: r.mat_doc_id)] == [1, 0]

    async def test_移除最後一份文件而無其他媒材時被擋(self, client, db) -> None:
        """檢核的是**存檔後的狀態**——這正是逐筆即時刪除會繞過的那一條。"""
        uid = await _user(db, "ETM_D6B")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000214")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000214"])

        r = await _put(client, uid, mid, doc_ids=[], version=1)
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_002"
        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert [d["doc_id"] for d in detail.json()["docs"]] == ["DM-TRAINING-000214"], "被擋下的請求須整批回滾"

    async def test_引用不存在之文件回_404(self, client, db) -> None:
        uid = await _user(db, "ETM_D7")
        mid = await _material(client, uid)
        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-999999"])
        assert r.status_code == 404

    async def test_引用非可引用分類之文件被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_D8")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-POLICY-000001", category="POLICY")
        r = await _put(client, uid, mid, doc_ids=["DM-POLICY-000001"])
        assert r.status_code == 404

    async def test_逐筆移除引用(self, client, db) -> None:
        uid = await _user(db, "ETM_D9")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000209")
        await _dm_doc(db, "DM-TRAINING-000210")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000209", "DM-TRAINING-000210"])

        r = await _put(client, uid, mid, doc_ids=["DM-TRAINING-000210"], version=1)
        assert r.status_code == 204, r.text
        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert [d["doc_id"] for d in detail.json()["docs"]] == ["DM-TRAINING-000210"]

    async def test_dm_端取不到時標記為_unavailable(self, client, db) -> None:
        """一筆壞掉的引用不該讓整個教材視窗打不開——標記出來讓教師自行移除。"""
        uid = await _user(db, "ETM_DA")
        mid = await _material(client, uid)
        await _dm_doc(db, "DM-TRAINING-000211")
        await _put(client, uid, mid, doc_ids=["DM-TRAINING-000211"])
        doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-TRAINING-000211"))
        doc.deleted = 1
        await db.flush()

        detail = await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))
        assert detail.status_code == 200, "單筆引用失效不應讓整個詳細頁失敗"
        assert detail.json()["docs"][0]["unavailable"] is True

    async def test_非擁有者不可更新(self, client, db) -> None:
        owner = await _user(db, "ETM_DB")
        other = await _user(db, "ETM_DC")
        mid = await _material(client, owner)
        await _dm_doc(db, "DM-TRAINING-000212")
        r = await _put(client, other, mid, doc_ids=["DM-TRAINING-000212"])
        assert r.status_code == 403


class TestDmDocumentOptions:
    async def test_下拉列出訓練教材(self, client, db) -> None:
        uid = await _user(db, "ETM_L1")
        await _dm_doc(db, "DM-TRAINING-000301", name="教育訓練手冊")
        r = await client.get("/api/et/dm-documents", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        assert "DM-TRAINING-000301" in [d["doc_id"] for d in r.json()]

    async def test_下拉不出現已廢止文件(self, client, db) -> None:
        uid = await _user(db, "ETM_L2")
        await _dm_doc(db, "DM-TRAINING-000302", status="OBSOLETE")
        r = await client.get("/api/et/dm-documents", headers=_bearer(uid))
        assert "DM-TRAINING-000302" not in [d["doc_id"] for d in r.json()]

    async def test_下拉仍出現廢止待簽核文件(self, client, db) -> None:
        """廢止待簽核期間仍屬有效，不應提前從可選清單移除。"""
        uid = await _user(db, "ETM_L3")
        await _dm_doc(db, "DM-TRAINING-000303", status="PENDING_OBSOLETE")
        r = await client.get("/api/et/dm-documents", headers=_bearer(uid))
        assert "DM-TRAINING-000303" in [d["doc_id"] for d in r.json()]

    async def test_關鍵字過濾(self, client, db) -> None:
        uid = await _user(db, "ETM_L4")
        await _dm_doc(db, "DM-TRAINING-000304", name="消防安全")
        await _dm_doc(db, "DM-TRAINING-000305", name="資訊安全")
        r = await client.get("/api/et/dm-documents", params={"keyword": "消防"}, headers=_bearer(uid))
        got = [d["doc_id"] for d in r.json()]
        assert "DM-TRAINING-000304" in got and "DM-TRAINING-000305" not in got

    async def test_超長關鍵字被擋(self, client, db) -> None:
        uid = await _user(db, "ETM_L5")
        r = await client.get("/api/et/dm-documents", params={"keyword": "x" * 200}, headers=_bearer(uid))
        assert r.status_code == 422
