"""已廢止文件查詢（US10 / UCDM08 / DM06）整合測試（真實 DB）。

涵蓋：DM_ADMIN 查詢已廢止清單（末版版號 + 廢止脈絡欄位：原作者〔末版作者〕/ 申請人 / 核准者 / 廢止時間 / 原因）、
關鍵字（文件名 / 廢止原因）/ 分類 / 廢止日期區間過濾、CSV 匯出（含 BOM + 跳脫）、
存取閘（非 DM_ADMIN 清單 + 匯出 403 DM_AUTH_003、access 回 false、未登入 401）、查無回空。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


def _headers(sub):
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _seed_user(db, user_id, name):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _obsolete_doc(
    db,
    doc_id,
    *,
    doc_name=None,
    version_no="1.0",
    author="author1",
    applicant="applicant1",
    approver="approver1",
    reason="流程停辦",
    complete_date=None,
    category="SOP",
):
    """建立一份已廢止文件：OBSOLETE 主檔 + 末版 PUBLISHED 版 + 核准之 OBSOLETE 週期。"""
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=doc_name or f"文件{doc_id}",
        category_code=category,
        status="OBSOLETE",
        created_user="orig_creator",
        created_date=utcnow(),
    )
    db.add(doc)
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
        created_user=author,
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    doc.current_version_id = v.version_id
    db.add(
        DmReview(
            doc_id=doc_id,
            version_id=v.version_id,
            review_type="OBSOLETE",
            assigned_reviewer=approver,
            approver_user_id=approver,
            status="APPROVED",
            submit_date=utcnow(),
            complete_date=complete_date or utcnow(),
            reason=reason,
            created_user=applicant,
            created_date=utcnow(),
        )
    )
    await db.flush()
    return doc, v


# ── 清單查詢 ──────────────────────────────────────────


async def test_admin_lists_obsolete_with_context_fields(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "author1", "原作者A")
    await _seed_user(db, "applicant1", "申請人B")
    await _seed_user(db, "approver1", "核准者C")
    await _obsolete_doc(db, "DM-SOP-000901", doc_name="停辦作業SOP", version_no="3.0", reason="部門裁撤")

    resp = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("adm"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    item = body["data"][0]
    assert item["doc_id"] == "DM-SOP-000901"
    assert item["doc_name"] == "停辦作業SOP"
    assert item["latest_version_no"] == "3.0"  # 末版版號
    assert item["category_code"] == "SOP"
    assert item["author_name"] == "原作者A"  # Q2=B：原作者＝末版作者
    assert item["applicant_name"] == "申請人B"  # 廢止申請人＝review.created_user
    assert item["approver_name"] == "核准者C"  # 核准者
    assert item["obsolete_reason"] == "部門裁撤"
    assert item["obsolete_date"] is not None


async def test_only_approved_obsolete_included(db, client):
    """PENDING_OBSOLETE（廢止待簽核仍在架）與 PUBLISHED 不入 DM06。"""
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "author1", "作者")
    await _seed_user(db, "applicant1", "申請")
    await _seed_user(db, "approver1", "核准")
    await _obsolete_doc(db, "DM-SOP-000902")
    # 一份仍在架（PUBLISHED）文件，不應出現
    pub = DmDocument(
        doc_id="DM-SOP-000903", doc_name="在架", category_code="SOP", status="PUBLISHED",
        created_user="x", created_date=utcnow(),
    )
    db.add(pub)
    await db.flush()

    resp = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("adm"))
    ids = [r["doc_id"] for r in resp.json()["data"]]
    assert "DM-SOP-000902" in ids and "DM-SOP-000903" not in ids


async def test_filter_by_keyword_name_or_reason(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    for uid in ("author1", "applicant1", "approver1"):
        await _seed_user(db, uid, uid)
    await _obsolete_doc(db, "DM-SOP-000904", doc_name="血袋標籤規範", reason="改版")
    await _obsolete_doc(db, "DM-SOP-000905", doc_name="採血流程", reason="血袋條碼汰換")

    # 關鍵字命中文件名
    r1 = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("adm"), params={"keyword": "血袋標籤"})
    assert [r["doc_id"] for r in r1.json()["data"]] == ["DM-SOP-000904"]
    # 關鍵字命中廢止原因
    r2 = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("adm"), params={"keyword": "條碼汰換"})
    assert [r["doc_id"] for r in r2.json()["data"]] == ["DM-SOP-000905"]


async def test_filter_by_date_range(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    for uid in ("author1", "applicant1", "approver1"):
        await _seed_user(db, uid, uid)
    old = datetime(2026, 1, 10, tzinfo=timezone.utc)
    new = datetime(2026, 6, 20, tzinfo=timezone.utc)
    await _obsolete_doc(db, "DM-SOP-000906", complete_date=old)
    await _obsolete_doc(db, "DM-SOP-000907", complete_date=new)

    resp = await client.get(
        "/api/dm/obsolete-archive/documents",
        headers=_headers("adm"),
        params={"date_from": "2026-05-01", "date_to": "2026-12-31"},
    )
    assert [r["doc_id"] for r in resp.json()["data"]] == ["DM-SOP-000907"]


async def test_filter_by_category(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    for uid in ("author1", "applicant1", "approver1"):
        await _seed_user(db, uid, uid)
    await _obsolete_doc(db, "DM-SOP-000910", category="SOP")
    await _obsolete_doc(db, "DM-TRAINING-000911", category="TRAINING")

    resp = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("adm"), params={"category": "SOP"})
    ids = [r["doc_id"] for r in resp.json()["data"]]
    assert "DM-SOP-000910" in ids and "DM-TRAINING-000911" not in ids


async def test_empty_result(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    resp = await client.get(
        "/api/dm/obsolete-archive/documents", headers=_headers("adm"), params={"keyword": "不存在關鍵字zzz"}
    )
    assert resp.status_code == 200 and resp.json()["data"] == [] and resp.json()["meta"]["total"] == 0


# ── 存取閘 ──────────────────────────────────────────


async def test_list_requires_auth(db, client):
    resp = await client.get("/api/dm/obsolete-archive/documents")
    assert resp.status_code == 401


async def test_list_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/obsolete-archive/documents", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


async def test_export_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/obsolete-archive/documents/export", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


async def test_access_flag_admin_vs_non_admin(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)

    r_adm = await client.get("/api/dm/obsolete-archive/access", headers=_headers("adm"))
    assert r_adm.status_code == 200 and r_adm.json()["can_access"] is True
    r_ed = await client.get("/api/dm/obsolete-archive/access", headers=_headers("ed"))
    assert r_ed.status_code == 200 and r_ed.json()["can_access"] is False


# ── CSV 匯出 ──────────────────────────────────────────


async def test_export_csv_content(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "author1", "原作者A")
    await _seed_user(db, "applicant1", "申請人B")
    await _seed_user(db, "approver1", "核准者C")
    # 原因含逗號 → 驗證 CSV 跳脫不破欄
    await _obsolete_doc(db, "DM-SOP-000908", doc_name="停辦SOP", reason="裁撤,合併")

    resp = await client.get("/api/dm/obsolete-archive/documents/export", headers=_headers("adm"))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8-sig")  # 去 BOM
    assert "DM-SOP-000908" in text and "停辦SOP" in text and "原作者A" in text
    assert '"裁撤,合併"' in text  # 含逗號欄位被雙引號包覆（csv 標準跳脫）
