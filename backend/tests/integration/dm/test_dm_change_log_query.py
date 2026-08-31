"""文件變更歷程查詢（US11 / UCDM10 / DM08）整合測試（真實 DB）。

涵蓋：DM_ADMIN 查 DM_CHANGE_LOG 發布 / 廢止事件（欄位：時間 / 申請人 / 核准人 / 操作 / 文件 / 版本 / 備註）、
日期區間 / 申請人or核准人（帳號或姓名）/ 操作類型過濾、CSV 匯出（BOM + 公式注入防護）、
存取閘（非 DM_ADMIN 清單 + 匯出 403 DM_AUTH_003、未登入 401）、查無回空；
共用 admin-access 端點（DM_ADMIN → can_access true、非管理者 false）。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.models import DmChangeLog, DmReview
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


async def _doc_with_version(db, doc_id, *, doc_name, version_no, author="author1"):
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=doc_name,
        category_code="SOP",
        status="PUBLISHED",
        created_user=author,
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
    await db.flush()
    return v.version_id


async def _change_log(db, doc_id, *, operation, version_id, applicant, approver, note, when=None):
    db.add(
        DmChangeLog(
            doc_id=doc_id,
            version_id=version_id,
            operation=operation,
            applicant_user_id=applicant,
            approver_user_id=approver,
            operation_time=when or utcnow(),
            note=note,
            created_user=approver,
            created_date=when or utcnow(),
        )
    )
    await db.flush()


async def _seed_publish(
    db, doc_id="DM-SOP-001101", *, doc_name="發布文件", version_no="1.0", note="首版發布", when=None
):
    for uid, name in (("author1", "作者甲"), ("applicant1", "申請乙"), ("approver1", "核准丙")):
        if not await db.scalar(select(DpUser.user_id).where(DpUser.user_id == uid)):
            await _seed_user(db, uid, name)
    vid = await _doc_with_version(db, doc_id, doc_name=doc_name, version_no=version_no)
    await _change_log(
        db,
        doc_id,
        operation="PUBLISH",
        version_id=vid,
        applicant="applicant1",
        approver="approver1",
        note=note,
        when=when,
    )


# ── 清單查詢 ──────────────────────────────────────────


async def test_admin_lists_change_log_with_fields(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_publish(db, "DM-SOP-001101", doc_name="領血SOP", version_no="2.0", note="補充異常通報")

    resp = await client.get("/api/dm/change-log/entries", headers=_headers("adm"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    item = body["data"][0]
    assert item["doc_id"] == "DM-SOP-001101"
    assert item["doc_name"] == "領血SOP"
    assert item["operation"] == "PUBLISH"
    assert item["version_no"] == "2.0"
    assert item["applicant_name"] == "申請乙"
    assert item["approver_name"] == "核准丙"
    assert item["note"] == "補充異常通報"
    assert item["operation_time"] is not None


async def test_filter_by_operation(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_publish(db, "DM-SOP-001102", note="發布")
    # 一筆廢止事件（重用同文件之版本）
    vid = await db.scalar(select(DmDocVersion.version_id).where(DmDocVersion.doc_id == "DM-SOP-001102"))
    await _change_log(
        db,
        "DM-SOP-001102",
        operation="OBSOLETE",
        version_id=vid,
        applicant="applicant1",
        approver="approver1",
        note="停辦",
    )

    r_pub = await client.get("/api/dm/change-log/entries", headers=_headers("adm"), params={"operation": "PUBLISH"})
    assert [e["operation"] for e in r_pub.json()["data"]] == ["PUBLISH"]
    r_obs = await client.get("/api/dm/change-log/entries", headers=_headers("adm"), params={"operation": "OBSOLETE"})
    assert [e["operation"] for e in r_obs.json()["data"]] == ["OBSOLETE"]
    # 全部（不帶 operation）→ 兩筆
    r_all = await client.get("/api/dm/change-log/entries", headers=_headers("adm"))
    assert r_all.json()["meta"]["total"] == 2
    assert {e["operation"] for e in r_all.json()["data"]} == {"PUBLISH", "OBSOLETE"}


async def test_filter_by_party_keyword_applicant_or_approver(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "zhang", "張三")
    await _seed_user(db, "li", "李四")
    await _seed_publish(db, "DM-SOP-001103", note="a")
    # 申請人 = 張三 之事件
    vid = await db.scalar(select(DmDocVersion.version_id).where(DmDocVersion.doc_id == "DM-SOP-001103"))
    await _change_log(
        db, "DM-SOP-001103", operation="OBSOLETE", version_id=vid, applicant="zhang", approver="li", note="b"
    )

    # 關鍵字比對申請人姓名
    r1 = await client.get("/api/dm/change-log/entries", headers=_headers("adm"), params={"keyword": "張三"})
    assert all(e["applicant_name"] == "張三" or e["approver_name"] == "張三" for e in r1.json()["data"])
    assert len(r1.json()["data"]) == 1
    # 關鍵字比對核准人姓名（「李四」不與其他 seed 帳號/姓名撞字）
    r2 = await client.get("/api/dm/change-log/entries", headers=_headers("adm"), params={"keyword": "李四"})
    assert len(r2.json()["data"]) == 1 and r2.json()["data"][0]["approver_name"] == "李四"


async def test_filter_by_date_range(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    old = datetime(2026, 1, 10, tzinfo=timezone.utc)
    new = datetime(2026, 6, 20, tzinfo=timezone.utc)
    await _seed_publish(db, "DM-SOP-001104", note="old", when=old)
    await _seed_publish(db, "DM-SOP-001105", note="new", when=new)

    resp = await client.get(
        "/api/dm/change-log/entries",
        headers=_headers("adm"),
        params={"date_from": "2026-05-01", "date_to": "2026-12-31"},
    )
    assert [e["doc_id"] for e in resp.json()["data"]] == ["DM-SOP-001105"]


async def test_empty_result(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    resp = await client.get("/api/dm/change-log/entries", headers=_headers("adm"), params={"keyword": "不存在zzz"})
    assert resp.status_code == 200 and resp.json()["data"] == [] and resp.json()["meta"]["total"] == 0


# ── 存取閘 ──────────────────────────────────────────


async def test_list_requires_auth(db, client):
    resp = await client.get("/api/dm/change-log/entries")
    assert resp.status_code == 401


async def test_list_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/change-log/entries", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


async def test_export_forbidden_for_non_admin(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    resp = await client.get("/api/dm/change-log/entries/export", headers=_headers("ed"))
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_003"


# ── 共用 admin-access（A' 收斂）──────────────────────


async def test_admin_access_flag(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)

    r_adm = await client.get("/api/dm/admin-access", headers=_headers("adm"))
    assert r_adm.status_code == 200 and r_adm.json()["can_access"] is True
    r_ed = await client.get("/api/dm/admin-access", headers=_headers("ed"))
    assert r_ed.status_code == 200 and r_ed.json()["can_access"] is False


# ── CSV 匯出 ──────────────────────────────────────────


async def test_export_csv_content(db, client):
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    # 備註含逗號 → 驗 CSV 跳脫不破欄
    await _seed_publish(db, "DM-SOP-001106", doc_name="停辦SOP", version_no="1.0", note="改版,重寫")

    resp = await client.get("/api/dm/change-log/entries/export", headers=_headers("adm"))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8-sig")
    assert "DM-SOP-001106" in text and "停辦SOP" in text and "核准丙" in text
    assert '"改版,重寫"' in text  # 含逗號欄位被雙引號包覆


async def test_export_csv_neutralizes_formula_injection(db, client):
    """CSV 公式注入防護（CWE-1236）：以 = / @ 開頭之自由輸入欄位匯出時前置單引號中和（比照 US10）。"""
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_publish(db, "DM-SOP-001107", doc_name="@cmd", note="=SUM(A1:A9)")

    resp = await client.get("/api/dm/change-log/entries/export", headers=_headers("adm"))
    text = resp.content.decode("utf-8-sig")
    assert "'=SUM(A1:A9)" in text and "'@cmd" in text  # 前置單引號 → 試算表視為文字


async def test_writing_and_reading_actions_not_logged(db, client):
    """回歸守門（AC5/AC6）：送審→退回不寫 DM_CHANGE_LOG——公開變更歷程僅含 PUBLISH/OBSOLETE。

    撰寫過程動作（上傳/編輯/送審/退回/撤回）與閱讀動作（下載/預覽）不入公開歷程，由資料來源保證；
    本測試走一次「送審→退回」流程驗證該文件不產生任何變更歷程列，防未來誤加寫入之回歸。
    """
    await _seed_user(db, "adm", "管理員")
    await _grant(db, "adm", DM_ADMIN)
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核")
    doc = DmDocument(
        doc_id="DM-SOP-001110",
        doc_name="退回文件",
        category_code="SOP",
        status="PENDING_REVIEW",
        created_user="ed",
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    v = DmDocVersion(
        doc_id="DM-SOP-001110",
        version_no="1.0",
        change_summary="摘要",
        file_name="f.pdf",
        file_path="/x/f.pdf",
        file_size=100,
        file_mime="application/pdf",
        status="PENDING_REVIEW",
        created_user="ed",
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    review = DmReview(
        doc_id="DM-SOP-001110",
        version_id=v.version_id,
        review_type="NEW",
        assigned_reviewer="rev1",
        status="PENDING",
        submit_date=utcnow(),
        created_user="ed",
        created_date=utcnow(),
    )
    db.add(review)
    await db.flush()

    # 退回（撰寫過程動作）→ 不應寫入公開變更歷程
    await ReviewCenterService().reject(db, review_id=review.review_id, reason="需補充", op=OperatorInfo(user_id="rev1"))

    cnt = await db.scalar(select(func.count()).select_from(DmChangeLog).where(DmChangeLog.doc_id == "DM-SOP-001110"))
    assert cnt == 0  # 送審/退回未寫 DM_CHANGE_LOG
    resp = await client.get("/api/dm/change-log/entries", headers=_headers("adm"))
    assert all(e["doc_id"] != "DM-SOP-001110" for e in resp.json()["data"])  # DM08 清單不含該文件
