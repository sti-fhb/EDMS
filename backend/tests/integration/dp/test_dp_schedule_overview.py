"""US11 排程總覽端點整合測試（唯讀）。

涵蓋 AC7：唯讀 job 清單 + 執行歷程分頁 + 無啟停 / 補跑端點（405）+ 未登入 401。
"""

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dp.schedules.repository import ScheduleRepository
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _seed_user(db, user_id="viewer"):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash="x",
            user_name="檢視者",
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


def _auth(user_id="viewer"):
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def test_list_schedules(client, db):
    """AC7：唯讀列出各 job（含種子 SCHDP001 + ET/DM 預留列）。"""
    await _seed_user(db)
    r = await client.get("/api/dp/schedules", headers=_auth())

    assert r.status_code == 200
    jobs = {j["job_id"]: j for j in r.json()}
    assert "SCHDP001" in jobs
    assert jobs["SCHDP001"]["cron_expr"] and "is_enabled" in jobs["SCHDP001"]


async def test_list_logs_paginated(client, db):
    """AC7：某 job 執行歷程（後端分頁）。"""
    await _seed_user(db)
    await ScheduleRepository().insert_log(
        db, job_id="SCHDP001", start_date=utcnow(), end_date=utcnow(), status="SUCCESS", error_msg=None
    )
    await db.commit()

    r = await client.get("/api/dp/schedules/SCHDP001/logs", headers=_auth())

    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "meta" in body
    assert any(log["status"] == "SUCCESS" for log in body["data"])


async def test_empty_logs(client, db):
    """AC7：無歷程 → 空 data（前端據此顯示 SCHEDULE-001）。"""
    await _seed_user(db)
    r = await client.get("/api/dp/schedules/SCHET001/logs", headers=_auth())

    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 0


async def test_no_collection_mutation_or_rerun(client, db):
    """集合層無新增 / 刪除、**無手動補跑端點**（補跑各模組自理，FR-03）；POST / DELETE / 集合 PUT 皆 405。"""
    await _seed_user(db)
    h = _auth()
    assert (await client.post("/api/dp/schedules", json={}, headers=h)).status_code == 405
    assert (await client.delete("/api/dp/schedules", headers=h)).status_code == 405
    assert (await client.put("/api/dp/schedules", json={}, headers=h)).status_code == 405
    # 無補跑端點
    assert (await client.post("/api/dp/schedules/SCHDP001/run", json={}, headers=h)).status_code == 404


async def test_list_includes_next_run(client, db):
    """#1：啟用中 job 回下次執行時間；停用 job 之 next_run 為 None。"""
    await _seed_user(db)
    r = await client.get("/api/dp/schedules", headers=_auth())
    jobs = {j["job_id"]: j for j in r.json()}

    assert jobs["SCHDP001"]["is_enabled"] is True and jobs["SCHDP001"]["next_run_date"] is not None
    assert jobs["SCHET001"]["is_enabled"] is False and jobs["SCHET001"]["next_run_date"] is None


async def test_update_schedule_edits_name_cron_enabled(client, db):
    """#4：PUT 編輯 JOB_NAME / CRON_EXPR / IS_ENABLED → 200 + DB 更新 + 稽核（func_name=DP-SCHEDULE）。"""
    from sqlalchemy import select

    from app.dp.audit.models import DpAuditLog
    from app.dp.schedules.repository import ScheduleRepository

    await _seed_user(db)
    r = await client.put(
        "/api/dp/schedules/SCHDP001",
        json={"job_name": "改名後的平台作業", "cron_expr": "30 2 * * *", "is_enabled": False},
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["job_name"] == "改名後的平台作業" and body["cron_expr"] == "30 2 * * *"
    assert body["is_enabled"] is False and body["next_run_date"] is None  # 停用 → 無下次執行

    job = await ScheduleRepository().get(db, "SCHDP001")
    assert job.job_name == "改名後的平台作業" and job.cron_expr == "30 2 * * *" and job.is_enabled is False

    audits = (await db.execute(select(DpAuditLog).where(DpAuditLog.func_name == "DP-SCHEDULE"))).scalars().all()
    assert any(a.target_id == "SCHDP001" and a.action_type == "UPDATE" for a in audits)


async def test_update_invalid_cron_422(client, db):
    """#4：cron 非法 → 422 DP_SCHED_002。"""
    await _seed_user(db)
    r = await client.put(
        "/api/dp/schedules/SCHDP001",
        json={"job_name": "x", "cron_expr": "不是合法cron", "is_enabled": True},
        headers=_auth(),
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "DP_SCHED_002"


async def test_update_not_found_404(client, db):
    """#4：job 不存在 → 404 DP_SCHED_001。"""
    await _seed_user(db)
    r = await client.put(
        "/api/dp/schedules/NOPE001",
        json={"job_name": "x", "cron_expr": "0 8 * * *", "is_enabled": True},
        headers=_auth(),
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "DP_SCHED_001"


async def test_cannot_edit_handler_ref(client, db):
    """#4 安全：body 無 HANDLER_REF/MODULE 欄位（schema 僅收 name/cron/is_enabled）→ 傳入亦被忽略、handler 不變。"""
    from app.dp.schedules.repository import ScheduleRepository

    await _seed_user(db)
    before = (await ScheduleRepository().get(db, "SCHDP001")).handler_ref
    r = await client.put(
        "/api/dp/schedules/SCHDP001",
        json={
            "job_name": "x",
            "cron_expr": "0 8 * * *",
            "is_enabled": True,
            "handler_ref": "os.system",
            "module": "XX",
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    after = (await ScheduleRepository().get(db, "SCHDP001")).handler_ref
    assert after == before  # HANDLER_REF 未被竄改


async def test_requires_auth(client):
    """未登入 → 401。"""
    assert (await client.get("/api/dp/schedules")).status_code == 401
