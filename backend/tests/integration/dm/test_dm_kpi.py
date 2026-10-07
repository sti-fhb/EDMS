"""閱讀統計 KPI 儀表板（US13 / UCDM13 / DM06）整合測試（真實 DB）。

涵蓋：DM_ADMIN 查逐文件 KPI（應看/已看/未看/率、目前版本、分類）、應看母體＝DM_VIEWER（純 EDITOR/ADMIN
不計）、audience「全體」vs 交集、已看∩應看、發新版重置、應看=0→rate None 且不計整體平均、統計卡
（整體平均 / below_50）、關鍵字 / 分類過濾、CSV（BOM + 公式注入防護）、存取閘（非 admin 403、未登入 401）、查無。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmFunc, DmTag  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _all_units_id(db):
    """單位組通用值「全單位」＝不限單位（#437 可見對象配對）。"""
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == "全單位"))


def _headers(sub):
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _tag_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == tag_name))


async def _seed_user(db, user_id, name, status="ACTIVE"):
    if await db.scalar(select(DpUser.user_id).where(DpUser.user_id == user_id)):
        return
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            status=status,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _grant_audience(db, user_id, tag_name, unit_name=None):
    """授予 (單位, 職位) 配對；`unit_name=None` 代表單位未指定（#437 導入前之既有授權形狀）。"""
    unit_id = None
    if unit_name is not None:
        unit_id = await db.scalar(
            select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == unit_name)
        )
    db.add(
        DmUserTag(
            user_id=user_id,
            tag_id=await _tag_id(db, tag_name),
            unit_tag_id=unit_id,
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _tag_doc_with_unit(db, doc_id, unit_name, tag_name):
    """文件掛指定 (單位, 職位) 配對（非通用值）。"""
    unit_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == unit_name))
    db.add(
        DmDocTag(
            doc_id=doc_id,
            tag_id=await _tag_id(db, tag_name),
            unit_tag_id=unit_id,
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _doc(db, doc_id, *, doc_name="文件", category="SOP", version_no="1.0", status="PUBLISHED"):
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=doc_name,
            category_code=category,
            status=status,
            created_user="author",
            created_date=utcnow(),
        )
    )
    await db.flush()
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name="f.pdf",
        file_path="/x/f.pdf",
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=utcnow(),
        created_user="author",
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    doc = await db.get(DmDocument, doc_id)
    doc.current_version_id = v.version_id
    await db.flush()
    return v.version_id


async def _tag_doc(db, doc_id, tag_name):
    db.add(
        DmDocTag(
            doc_id=doc_id,
            tag_id=await _tag_id(db, tag_name),
            unit_tag_id=await _all_units_id(db),  # 「全單位」＝不限單位（#437 配對語意）
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _read(db, doc_id, version_id, user_id):
    db.add(DmDocRead(doc_id=doc_id, version_id=version_id, created_user=user_id, created_date=utcnow()))
    await db.flush()


async def _seed_admin(db, uid="adm"):
    await _seed_user(db, uid, "管理員")
    await _grant(db, uid, DM_ADMIN)


# ── 逐文件 KPI 值 ─────────────────────────────────────


async def test_admin_lists_kpi_fields(db, client):
    await _seed_admin(db)
    await _seed_user(db, "v1", "閱覽甲")
    await _grant(db, "v1", DM_VIEWER)
    await _grant_audience(db, "v1", "護理師")
    vid = await _doc(db, "DM-SOP-000101", doc_name="領血SOP", version_no="2.0")
    await _tag_doc(db, "DM-SOP-000101", "護理師")
    await _read(db, "DM-SOP-000101", vid, "v1")

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    assert resp.status_code == 200
    body = resp.json()
    item = next(d for d in body["data"] if d["doc_id"] == "DM-SOP-000101")
    assert item["doc_name"] == "領血SOP"
    assert item["current_version_no"] == "2.0"
    assert item["category_name"] is not None
    assert item["should_see"] == 1
    assert item["seen"] == 1
    assert item["unseen"] == 0
    assert item["rate"] == 1.0


async def test_should_see_all_audience_counts_all_viewers(db, client):
    await _seed_admin(db)
    for uid in ("v1", "v2", "v3"):
        await _seed_user(db, uid, uid)
        await _grant(db, uid, DM_VIEWER)
    await _doc(db, "DM-SOP-000102")
    await _tag_doc(db, "DM-SOP-000102", "全體")

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000102")
    assert item["should_see"] == 3  # 掛「全體」→ 全部 DM_VIEWER


async def test_should_see_intersection(db, client):
    await _seed_admin(db)
    await _seed_user(db, "nurse", "護")
    await _grant(db, "nurse", DM_VIEWER)
    await _grant_audience(db, "nurse", "護理師")
    await _seed_user(db, "soldier", "軍")
    await _grant(db, "soldier", DM_VIEWER)
    await _grant_audience(db, "soldier", "軍人")
    await _doc(db, "DM-SOP-000103")
    await _tag_doc(db, "DM-SOP-000103", "護理師")

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000103")
    assert item["should_see"] == 1  # 僅護理師閱覽者相符，軍人不計


async def test_pure_editor_not_in_should_see(db, client):
    """SA 裁示：純 EDITOR/ADMIN 無 VIEWER 者不計入應看，即使可見對象相符。"""
    await _seed_admin(db)
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    await _grant_audience(db, "ed", "護理師")  # 有可見對象但無 VIEWER 角色
    await _doc(db, "DM-SOP-000104")
    await _tag_doc(db, "DM-SOP-000104", "護理師")

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000104")
    assert item["should_see"] == 0  # 純編輯者不計入應看


async def test_seen_intersects_should_see(db, client):
    """已看＝應看∩下載者：非應看之下載者（如編輯者下載）不計入已看。"""
    await _seed_admin(db)
    await _seed_user(db, "v1", "閱覽")
    await _grant(db, "v1", DM_VIEWER)
    await _grant_audience(db, "v1", "護理師")
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    vid = await _doc(db, "DM-SOP-000105")
    await _tag_doc(db, "DM-SOP-000105", "護理師")
    await _read(db, "DM-SOP-000105", vid, "ed")  # 編輯者下載（非應看）

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000105")
    assert item["should_see"] == 1 and item["seen"] == 0 and item["unseen"] == 1


async def test_new_version_resets_seen(db, client):
    """發布新版本後，僅下載舊版者對新版視為未看（已看綁目前發布版）。"""
    await _seed_admin(db)
    await _seed_user(db, "v1", "閱覽")
    await _grant(db, "v1", DM_VIEWER)
    await _grant_audience(db, "v1", "護理師")
    v1 = await _doc(db, "DM-SOP-000106", version_no="1.0")
    await _tag_doc(db, "DM-SOP-000106", "護理師")
    await _read(db, "DM-SOP-000106", v1, "v1")  # 讀了 v1
    # 發布 v2 並設為目前版
    v2 = DmDocVersion(
        doc_id="DM-SOP-000106",
        version_no="2.0",
        change_summary="改版",
        file_name="f.pdf",
        file_path="/x/f2.pdf",
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=utcnow(),
        created_user="author",
        created_date=utcnow(),
    )
    db.add(v2)
    await db.flush()
    doc = await db.get(DmDocument, "DM-SOP-000106")
    doc.current_version_id = v2.version_id
    await db.flush()

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000106")
    assert item["seen"] == 0 and item["unseen"] == 1 and item["rate"] == 0.0


async def test_disabled_viewer_excluded_from_should_see(db, client):
    """停用（STATUS=DISABLED）之閱覽者無法登入閱讀，不列入應看分母（不永久拉低閱讀率）。"""
    await _seed_admin(db)
    await _seed_user(db, "v_active", "有效")
    await _grant(db, "v_active", DM_VIEWER)
    await _grant_audience(db, "v_active", "護理師")
    await _seed_user(db, "v_disabled", "停用", status="DISABLED")
    await _grant(db, "v_disabled", DM_VIEWER)
    await _grant_audience(db, "v_disabled", "護理師")
    await _doc(db, "DM-SOP-000130")
    await _tag_doc(db, "DM-SOP-000130", "護理師")

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    item = next(d for d in body["data"] if d["doc_id"] == "DM-SOP-000130")
    assert item["should_see"] == 1  # 僅 v_active；停用之 v_disabled 不計


async def test_pending_obsolete_doc_included(db, client):
    """在架母體含 PENDING_OBSOLETE（廢止待簽核仍可下載、累積已看）；OBSOLETE / 送審不計。"""
    await _seed_admin(db)
    await _seed_user(db, "v1", "閱覽")
    await _grant(db, "v1", DM_VIEWER)
    await _grant_audience(db, "v1", "護理師")
    # 廢止待簽核文件（仍在架）
    vid = await _doc(db, "DM-SOP-000120", status="PENDING_OBSOLETE")
    await _tag_doc(db, "DM-SOP-000120", "護理師")
    await _read(db, "DM-SOP-000120", vid, "v1")
    # 已下架 / 送審中文件不列入
    await _doc(db, "DM-SOP-000121", status="OBSOLETE")
    await _doc(db, "DM-SOP-000122", status="PENDING_REVIEW")

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    ids = {d["doc_id"] for d in body["data"]}
    assert "DM-SOP-000120" in ids  # PENDING_OBSOLETE 納入
    assert "DM-SOP-000121" not in ids and "DM-SOP-000122" not in ids
    item = next(d for d in body["data"] if d["doc_id"] == "DM-SOP-000120")
    assert item["should_see"] == 1 and item["seen"] == 1 and item["rate"] == 1.0


async def test_zero_audience_rate_none_and_excluded_from_overall(db, client):
    """應看=0 → rate None（顯示「—」），且不列入整體平均。"""
    await _seed_admin(db)
    await _seed_user(db, "nurse", "護")
    await _grant(db, "nurse", DM_VIEWER)
    await _grant_audience(db, "nurse", "護理師")
    # 文件掛「軍人」但無任何軍人閱覽者 → 應看=0
    await _doc(db, "DM-SOP-000107")
    await _tag_doc(db, "DM-SOP-000107", "軍人")
    # 另一份護理師文件、已看 → rate 1.0
    v = await _doc(db, "DM-SOP-000108")
    await _tag_doc(db, "DM-SOP-000108", "護理師")
    await _read(db, "DM-SOP-000108", v, "nurse")

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    zero = next(d for d in body["data"] if d["doc_id"] == "DM-SOP-000107")
    assert zero["should_see"] == 0 and zero["rate"] is None
    # 整體平均只計 000108（1.0），排除應看=0 之 000107
    assert body["summary"]["overall_rate"] == 1.0


async def test_summary_overall_rate_and_below_50(db, client):
    await _seed_admin(db)
    for uid in ("a", "b"):
        await _seed_user(db, uid, uid)
        await _grant(db, uid, DM_VIEWER)
        await _grant_audience(db, uid, "護理師")
    # 文件 X：2 應看、1 已看 → 0.5（< 50%? 0.5 不 < 0.5，不算 below_50）
    vx = await _doc(db, "DM-SOP-000109")
    await _tag_doc(db, "DM-SOP-000109", "護理師")
    await _read(db, "DM-SOP-000109", vx, "a")
    # 文件 Y：2 應看、0 已看 → 0.0（< 50%）
    await _doc(db, "DM-SOP-000110")
    await _tag_doc(db, "DM-SOP-000110", "護理師")

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    assert body["summary"]["overall_rate"] == pytest.approx(0.25)  # (0.5 + 0.0)/2
    assert body["summary"]["below_50_count"] == 1  # 僅 Y（0.0）；X 之 0.5 不算


async def test_filter_keyword_and_category(db, client):
    await _seed_admin(db)
    await _doc(db, "DM-SOP-000111", doc_name="領血作業", category="SOP")
    await _doc(db, "DM-SOP-000112", doc_name="捐血須知", category="SOP")

    r_kw = await client.get("/api/dm/kpi/documents", headers=_headers("adm"), params={"keyword": "領血"})
    assert [d["doc_id"] for d in r_kw.json()["data"]] == ["DM-SOP-000111"]
    r_cat = await client.get("/api/dm/kpi/documents", headers=_headers("adm"), params={"category": "SOP"})
    assert {"DM-SOP-000111", "DM-SOP-000112"} <= {d["doc_id"] for d in r_cat.json()["data"]}


async def test_export_csv_and_formula_injection(db, client):
    await _seed_admin(db)
    await _doc(db, "DM-SOP-000113", doc_name="=SUM(A1:A9)")  # 公式注入嘗試於文件名
    resp = await client.get("/api/dm/kpi/documents/export", headers=_headers("adm"))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8-sig")
    assert "DM-SOP-000113" in text
    assert "'=SUM(A1:A9)" in text  # 前置單引號中和（CWE-1236）


async def test_empty_result(db, client):
    await _seed_admin(db)
    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"), params={"keyword": "不存在zzz"})
    assert resp.status_code == 200 and resp.json()["data"] == [] and resp.json()["summary"]["total_docs"] == 0


# ── 存取閘 ─────────────────────────────────────────────


async def test_requires_auth(db, client):
    assert (await client.get("/api/dm/kpi/documents")).status_code == 401


async def test_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/kpi/documents", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


async def test_export_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/kpi/documents/export", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


async def test_should_see_母體依配對計算_不含其他單位同職位(db, client):
    """應看母體須依 (單位, 職位) 整組判定（#437）。

    若沿用配對化前的「只比職位」，掛「軍醫局 + 護理師」的文件會把**所有單位的護理師**算進母體：
    KPI 閱讀率被稀釋成假的低分，而每週的未讀提醒（含 doc_name）會寄給看不到該文件的人。
    """
    await _seed_admin(db)
    await _seed_user(db, "kpi_mab_nurse", "軍醫局護理")
    await _seed_user(db, "kpi_tsgh_nurse", "三總護理")
    await _grant(db, "kpi_mab_nurse", DM_VIEWER)
    await _grant(db, "kpi_tsgh_nurse", DM_VIEWER)
    await _grant_audience(db, "kpi_mab_nurse", "護理師", "國防部軍醫局")
    await _grant_audience(db, "kpi_tsgh_nurse", "護理師", "國防醫學院三軍總醫院")
    await _doc(db, "DM-SOP-000600")
    await _tag_doc_with_unit(db, "DM-SOP-000600", "國防部軍醫局", "護理師")

    resp = await client.get("/api/dm/kpi/documents", headers=_headers("adm"))

    assert resp.status_code == 200
    item = next(d for d in resp.json()["data"] if d["doc_id"] == "DM-SOP-000600")
    assert item["should_see"] == 1  # 只有軍醫局的護理師；三總的護理師不算


# ── #567：逐組明細 / 訓練教材分區 / 統計卡分母 ───────────


async def test_逐組明細隨清單回傳(db, client):
    """一份文件掛兩組 → `data[].groups` 逐組給完成度（#567 A）。

    ⚠️ 文件總計去重、逐組各自計算，故此處 2 + 1 = 3 恰等於總計僅因無人身兼兩職；
    身兼兩職之案例由 `tests/unit/dm/test_dm_kpi_audience_groups.py` 釘住。
    """
    await _seed_admin(db)
    for uid, role in (("n1", "護理師"), ("n2", "護理師"), ("t1", "醫檢師")):
        await _seed_user(db, uid, uid)
        await _grant(db, uid, DM_VIEWER)
        await _grant_audience(db, uid, role)
    v = await _doc(db, "DM-SOP-000120")
    await _tag_doc(db, "DM-SOP-000120", "護理師")
    await _tag_doc(db, "DM-SOP-000120", "醫檢師")
    await _read(db, "DM-SOP-000120", v, "n1")

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    doc = next(d for d in body["data"] if d["doc_id"] == "DM-SOP-000120")
    groups = {g["label"]: g for g in doc["groups"]}
    assert (groups["護理師"]["should_see"], groups["護理師"]["seen"]) == (2, 1)
    assert (groups["醫檢師"]["should_see"], groups["醫檢師"]["seen"]) == (1, 0)
    assert groups["醫檢師"]["rate"] == 0.0
    assert doc["should_see"] == 3


async def test_rated_docs_只計可算閱讀率之文件(db, client):
    """`below_50_count` 的分母是 `rated_docs` 而非 `total_docs`（#567 C）。"""
    await _seed_admin(db)
    await _seed_user(db, "n1", "n1")
    await _grant(db, "n1", DM_VIEWER)
    await _grant_audience(db, "n1", "護理師")
    await _doc(db, "DM-SOP-000121")
    await _tag_doc(db, "DM-SOP-000121", "護理師")  # 應看 1 → 可計算
    await _doc(db, "DM-SOP-000122")
    await _tag_doc(db, "DM-SOP-000122", "軍人")  # 無軍人閱覽者 → 應看 0、不可計算

    s = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()["summary"]
    assert s["total_docs"] == 2
    assert s["rated_docs"] == 1


async def test_training_不入統計清單_另成訓練教材區(db, client):
    """訓練教材移出統計母體、另成一區且**不帶任何統計欄位**（#567 B）。"""
    await _seed_admin(db)
    await _doc(db, "DM-SOP-000123", doc_name="領血SOP", category="SOP")
    await _doc(db, "DM-TRAINING-000902", doc_name="基礎輸血學", category="TRAINING")
    await _tag_doc(db, "DM-TRAINING-000902", "護理師")  # 既有教材帶可見對象之形狀（#377 之前）

    body = (await client.get("/api/dm/kpi/documents", headers=_headers("adm"))).json()
    assert [d["doc_id"] for d in body["data"]] == ["DM-SOP-000123"]
    assert body["summary"]["total_docs"] == 1
    assert [t["doc_id"] for t in body["training_docs"]] == ["DM-TRAINING-000902"]
    assert body["training_total"] == 1
    # 該區給了統計數字就是給出保證低報的值，故逐欄釘死
    assert set(body["training_docs"][0]) == {"doc_id", "doc_name", "category_name", "current_version_no"}


async def test_csv_不含訓練教材(db, client):
    await _seed_admin(db)
    await _doc(db, "DM-SOP-000124", doc_name="領血SOP", category="SOP")
    await _doc(db, "DM-TRAINING-000903", doc_name="基礎輸血學", category="TRAINING")

    text = (await client.get("/api/dm/kpi/documents/export", headers=_headers("adm"))).content.decode("utf-8-sig")
    assert "DM-SOP-000124" in text
    assert "DM-TRAINING-000903" not in text
