"""US11 排程總覽端點整合測試（唯讀）。

涵蓋 AC7：唯讀 job 清單 + 執行歷程分頁 + 無啟停 / 補跑端點（405）+ 未登入 401。
"""

import re

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.scheduler import next_run
from app.dp.users.models import DpUser

# usefixtures(backoffice_admin)：本檔驗後台功能之業務邏輯，非授權；#250 起後台 router
# 掛 require_any_module_admin，故統一讓操作者通過該閘（授權行為見 test_dp_backoffice_gate.py）
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("backoffice_admin")]


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


async def test_list_schedules_returns_description(client, db):
    """#311：回傳說明欄，且 JOB_NAME 已拆短（工作內容改由 DESCRIPTION 承載）。

    原本沒有說明欄，管理者只能靠 JOB_NAME 判斷 job 在做什麼——SCHDP001 因此被塞成
    「平台每日作業（閒置帳號禁用 + 密碼到期提醒 + 清理逾期待驗證列）」，每次工作內容
    變動都得改那串字並開一支 migration（見 070865346fb4）。
    """
    await _seed_user(db)
    r = await client.get("/api/dp/schedules", headers=_auth())

    assert r.status_code == 200
    jobs = {j["job_id"]: j for j in r.json()}
    dp001 = jobs["SCHDP001"]
    assert dp001["job_name"] == "平台每日作業"  # 拆短：不再承載工作內容細節
    # 三批工作內容移入說明（原本全塞在 JOB_NAME 裡）
    desc = dp001["description"] or ""
    assert "閒置" in desc and "密碼" in desc and "待驗證" in desc


@pytest.mark.parametrize("job_id", ["SCHDM001", "SCHET001"])
async def test_週報排程實際觸發日為週一(client, db, job_id):
    """#332：兩支週報的 CRON_EXPR 必須**真的**落在週一。

    釘的是**實際觸發日**而非 cron 字串。原本兩支都是 `0 10 * * 1`，而規格、說明欄、
    已移除的 `DM_WEEKLY_SCHED_DAY_TIME`（`週一,10:00`）全寫「週一」——但 APScheduler 的
    day-of-week 以週一為 0，`1` 是**週二**，於是兩支週報整整晚一天跑了一段時間。

    沒有任何測試釘住觸發日，是它能活這麼久的原因：cron 字串看起來「很像」週一。
    若日後有人把 `0` 改回比較直覺的 `1`，這裡會紅。
    """
    await _seed_user(db)
    r = await client.get("/api/dp/schedules", headers=_auth())

    job = {j["job_id"]: j for j in r.json()}[job_id]
    fire = next_run(job["cron_expr"])
    assert fire is not None, f"{job_id} 的 cron 無法解析：{job['cron_expr']}"
    assert fire.weekday() == 0, (
        f"{job_id} 的 {job['cron_expr']} 觸發於 {fire:%Y-%m-%d}（週{'一二三四五六日'[fire.weekday()]}），應為週一"
    )
    assert (fire.hour, fire.minute) == (10, 0)


async def test_說明欄不再承載執行時點(client, db):
    """#332：執行時點的唯一事實來源是 `CRON_EXPR`，說明欄只描述職責。

    原本五筆說明欄都以「每日 08:00 執行，」「每週一 10:00 執行，」開頭，而 `CRON_EXPR`
    可由管理者在**同一個畫面**上改，兩者沒有同步機制。已經歪過一次：`SCHDM001` 的 cron
    於 `9eb4dd6e496b` 改為 10:00，12 天後回填說明欄的 `b3f7c2e8a591` 抄的仍是舊的 08:00。

    斷言的是「不含時鐘時間」而非比對整串文字——後者會在每次改文案時假性轉紅，卻擋不住
    真正的問題（有人又把時點寫回去）。
    """
    await _seed_user(db)
    r = await client.get("/api/dp/schedules", headers=_auth())

    for job in r.json():
        desc = job["description"] or ""
        assert not re.search(r"\d{1,2}:\d{2}", desc), f"{job['job_id']} 的說明欄仍寫著執行時點：{desc}"
        assert desc, f"{job['job_id']} 的說明欄不應為空"


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
    """#1：啟用中 job 回下次執行時間；停用 job 之 next_run 為 None。

    停用側以**本測試自己停用**的 job 驗，不借用某一列 seed 當下剛好是停用——那種寫法會
    在該 job 日後被接線啟用時無預警轉紅（#325 接上 SCHET001 時即如此）。
    """
    from sqlalchemy import update

    from app.dp.schedules.models import DpSchedule

    await _seed_user(db)
    await db.execute(update(DpSchedule).where(DpSchedule.job_id == "SCHDM002").values(is_enabled=False))
    await db.flush()

    r = await client.get("/api/dp/schedules", headers=_auth())
    jobs = {j["job_id"]: j for j in r.json()}

    assert jobs["SCHDP001"]["is_enabled"] is True and jobs["SCHDP001"]["next_run_date"] is not None
    assert jobs["SCHDM002"]["is_enabled"] is False and jobs["SCHDM002"]["next_run_date"] is None


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
