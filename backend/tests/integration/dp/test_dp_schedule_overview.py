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


async def test_no_mutation_endpoints(client, db):
    """AC7：唯讀——集合無啟停 / 補跑，POST / PUT / DELETE 皆 405。"""
    await _seed_user(db)
    h = _auth()
    assert (await client.post("/api/dp/schedules", json={}, headers=h)).status_code == 405
    assert (await client.put("/api/dp/schedules", json={}, headers=h)).status_code == 405
    assert (await client.delete("/api/dp/schedules", headers=h)).status_code == 405


async def test_requires_auth(client):
    """未登入 → 401。"""
    assert (await client.get("/api/dp/schedules")).status_code == 401
