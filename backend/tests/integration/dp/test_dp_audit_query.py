"""US10 操作記錄查詢整合測試（dp-audit，唯讀）。

多以 AuditQueryService + 真實 DB 直測業務規則；另抽樣 HTTP 驗 router 接線、認證與無刪改端點。
涵蓋 AC1（多條件 + 分頁時間倒序）/ AC2（明細前後值 + result/description）/ AC3（CSV 與查詢一致）/
AC5（無刪改端點）/ AC6（跨模組事件同表可查）/ AC7 interim（未登入被擋）。
"""

from datetime import datetime, timezone

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.audit.query_service import AuditQueryService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_service = AuditQueryService()


async def _insert_log(
    db,
    *,
    module="DP",
    func_name="DP-USERS",
    action_type="UPDATE",
    result="SUCCESS",
    operator_id="admin01",
    target_id=None,
    description=None,
    before_value=None,
    after_value=None,
    source_ip=None,
    created_date=None,
    row_hash=None,
):
    """直接插入一列稽核（查詢頁不驗鏈，row_hash 給佔位值即可，並可指定 created_date 測期間）。"""
    log = DpAuditLog(
        module=module,
        func_name=func_name,
        action_type=action_type,
        result=result,
        target_id=target_id,
        description=description,
        before_value=before_value,
        after_value=after_value,
        source_ip=source_ip,
        row_hash=row_hash or ("0" * 64),
        created_user=operator_id,
        created_date=created_date or utcnow(),
    )
    db.add(log)
    await db.flush()
    return log


async def _seed_user(db, *, user_id, user_name, email, deleted=0):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash="x",
            user_name=user_name,
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
            deleted=deleted,
        )
    )
    await db.flush()


def _q(**kw):
    base = dict(
        operator=None,
        module=None,
        action_type=None,
        result=None,
        date_from=None,
        date_to=None,
        page=1,
        limit=20,
    )
    base.update(kw)
    return base


# ── AC1：多條件查詢 + 後端分頁 + 時間倒序 ─────────────────────────────────


async def test_query_orders_by_time_desc(db):
    """AC1：結果依 CREATED_DATE 倒序（新→舊）。"""
    old = await _insert_log(db, created_date=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc))
    new = await _insert_log(db, created_date=datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc))

    res = await _service.query_logs(db, **_q())

    ids = [r.log_id for r in res["data"]]
    assert ids.index(new.log_id) < ids.index(old.log_id)


async def test_query_filters_by_module_action_result(db):
    """AC1：module / action_type / result 條件精確過濾。"""
    await _insert_log(db, module="DP", action_type="LOGIN", result="SUCCESS")
    await _insert_log(db, module="ET", action_type="CREATE", result="SUCCESS")
    target = await _insert_log(db, module="DP", action_type="LOGIN", result="FAIL")

    res = await _service.query_logs(db, **_q(module="DP", action_type="LOGIN", result="FAIL"))

    assert [r.log_id for r in res["data"]] == [target.log_id]


async def test_query_filters_by_date_range_inclusive(db):
    """AC1：date_to 含當日全天（以隔日 00:00 為上界）。"""
    await _insert_log(db, created_date=datetime(2026, 6, 30, 23, 0, tzinfo=timezone.utc))
    inside = await _insert_log(db, created_date=datetime(2026, 7, 5, 23, 59, tzinfo=timezone.utc))
    await _insert_log(db, created_date=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc))

    from datetime import date

    res = await _service.query_logs(db, **_q(date_from=date(2026, 7, 1), date_to=date(2026, 7, 5)))

    assert [r.log_id for r in res["data"]] == [inside.log_id]


async def test_query_pagination_meta(db):
    """AC1：後端分頁 meta 正確。"""
    for _ in range(5):
        await _insert_log(db)

    res = await _service.query_logs(db, **_q(limit=2, page=1))

    assert res["meta"]["total"] == 5
    assert res["meta"]["total_pages"] == 3
    assert len(res["data"]) == 2


async def test_query_operator_search_by_name(db):
    """AC1：operator 條件對 姓名 / Email 模糊比對（join DP_USER）。"""
    await _seed_user(db, user_id="u001", user_name="陳大華", email="chen@example.com")
    hit = await _insert_log(db, operator_id="u001")
    await _insert_log(db, operator_id="u999")  # 無此使用者

    res = await _service.query_logs(db, **_q(operator="大華"))

    assert [r.log_id for r in res["data"]] == [hit.log_id]
    assert res["data"][0].operator_name == "陳大華"


async def test_operator_search_matches_soft_deleted_user(db):
    """AC1：以已軟刪除（deleted=1）使用者之姓名搜尋，仍命中其歷史稽核並解析當時姓名。

    稽核為歷史留痕：operator join / 搜尋子查詢皆刻意不濾 DP_USER.deleted。
    """
    await _seed_user(db, user_id="gone01", user_name="離職者", email="gone@example.com", deleted=1)
    hit = await _insert_log(db, operator_id="gone01")

    res = await _service.query_logs(db, **_q(operator="離職"))

    assert [r.log_id for r in res["data"]] == [hit.log_id]
    assert res["data"][0].operator_name == "離職者"


# ── AC2：明細欄位（含 result / description / 前後值）────────────────────────


async def test_detail_fields_present(db):
    """AC2：明細含 result / description / before / after。"""
    await _insert_log(
        db,
        operator_id="u001",
        result="SUCCESS",
        description="手動解鎖帳號",
        before_value='{"status": "LOCKED"}',
        after_value='{"status": "ACTIVE"}',
        source_ip="10.1.2.33",
        target_id="USER:1042",
    )

    res = await _service.query_logs(db, **_q())
    row = res["data"][0]

    assert row.result == "SUCCESS"
    assert row.description == "手動解鎖帳號"
    assert row.before_value == '{"status": "LOCKED"}'
    assert row.after_value == '{"status": "ACTIVE"}'
    assert row.source_ip == "10.1.2.33"
    assert row.target_id == "USER:1042"


async def test_operator_name_none_for_unknown_user(db):
    """AC2：操作者為 SYSTEM / 不存在之 USER_ID 時 operator_name 為 None（不濾掉該列）。"""
    await _insert_log(db, operator_id="SYSTEM")

    res = await _service.query_logs(db, **_q())

    assert res["data"][0].operator_id == "SYSTEM"
    assert res["data"][0].operator_name is None


# ── AC3：CSV 匯出與查詢一致 ────────────────────────────────────────────────


async def test_export_csv_matches_query(db):
    """AC3：CSV 依條件全量、內容與查詢一致（含 BOM 與中文標頭）。"""
    await _insert_log(db, module="DP", result="SUCCESS")
    await _insert_log(db, module="ET", result="FAIL")

    csv_text = await _service.export_csv(
        db, operator=None, module="ET", action_type=None, result=None, date_from=None, date_to=None
    )

    assert csv_text.startswith("﻿")  # UTF-8 BOM
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert "執行結果" in lines[0] and "事件描述" in lines[0]
    # 標頭 + 1 筆 ET（module=ET 過濾）
    assert len(lines) == 2
    assert "ET" in lines[1]


async def test_export_csv_formula_injection_sanitized(db):
    """AC3 / 安全：CSV cell 以危險字元開頭者前置單引號（formula injection 防護）。"""
    await _insert_log(db, description="=1+2", func_name="DP-X")

    csv_text = await _service.export_csv(
        db, operator=None, module=None, action_type=None, result=None, date_from=None, date_to=None
    )

    assert "'=1+2" in csv_text
    assert "\n=1+2" not in csv_text


# ── AC6：跨模組資安事件同表可查 ────────────────────────────────────────────


async def test_cross_module_events_queryable(db):
    """AC6：ET / DM 資安事件寫入同表，可經 module 條件查得。"""
    await _insert_log(db, module="ET", func_name="ET-ROLE", action_type="UPDATE")
    await _insert_log(db, module="DM", func_name="DM-DOC", action_type="DELETE")

    et = await _service.query_logs(db, **_q(module="ET"))
    dm = await _service.query_logs(db, **_q(module="DM"))

    assert et["meta"]["total"] == 1 and et["data"][0].module == "ET"
    assert dm["meta"]["total"] == 1 and dm["data"][0].module == "DM"


# ── HTTP：router 接線 / 認證 / 無刪改端點 ─────────────────────────────────


async def test_query_endpoint_requires_auth(client):
    """AC7 interim：未帶 token → 401（管理者細分待 T049）。"""
    r = await client.get("/api/dp/audit/logs")
    assert r.status_code == 401


async def test_query_endpoint_authed_ok(client, db):
    """HTTP happy path：帶 token（sub 為存在之啟用帳號）→ 200 + 分頁結構。"""
    await _seed_user(db, user_id="auditor", user_name="稽核員", email="auditor@edms.local")
    await _insert_log(db, module="DP")
    headers = {"Authorization": f"Bearer {create_access_token(sub='auditor', ttl_minutes=15)}"}

    r = await client.get("/api/dp/audit/logs", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "meta" in body


async def test_export_endpoint_returns_csv(client, db):
    """AC3 HTTP：/logs/export 回 text/csv 附件。"""
    await _seed_user(db, user_id="auditor", user_name="稽核員", email="auditor@edms.local")
    await _insert_log(db, module="DP")
    headers = {"Authorization": f"Bearer {create_access_token(sub='auditor', ttl_minutes=15)}"}

    r = await client.get("/api/dp/audit/logs/export", headers=headers)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")


async def test_no_mutation_endpoints(client, db):
    """AC5：append-only——集合 /logs 僅允許 GET，POST / PUT / DELETE 皆 405。"""
    await _seed_user(db, user_id="auditor", user_name="稽核員", email="auditor@edms.local")
    headers = {"Authorization": f"Bearer {create_access_token(sub='auditor', ttl_minutes=15)}"}

    r_post = await client.post("/api/dp/audit/logs", json={}, headers=headers)
    r_put = await client.put("/api/dp/audit/logs", json={}, headers=headers)
    r_delete = await client.delete("/api/dp/audit/logs", headers=headers)

    assert r_post.status_code == 405
    assert r_put.status_code == 405
    assert r_delete.status_code == 405
