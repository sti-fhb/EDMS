"""T051 排程端到端整合測試（SC-011）。

聚焦跨概念串接（單點行為由 test_dp_schedule_engine / _schdp001 覆蓋）：
- **跨 job 失敗隔離**：一個 job handler 拋例外標 FAILED，另一 job 照常 SUCCESS，各自獨立記錄。
- **重疊跳過**：write_skipped_log 寫 SKIPPED 歷程（前次未完成不重複執行）。
- **SCHDP001 雙職責組合**：同批資料下閒置禁用 + 到期提醒兩職責同時生效（每日作業的完整授權）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

import app.dp.schedules.scheduler as scheduler_mod
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.notify.models import DpEmailLog
from app.dp.schedules.models import DpScheduleLog
from app.dp.schedules.scheduler import run_and_log, write_skipped_log
from app.dp.users.models import DpUser
from app.dp.users.repository import UsersRepository
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_HANDLER_MOD = "tests.integration.dp.test_dp_e2e_schedule"


async def _ok_handler() -> None:
    """成功 handler（無副作用）。"""


async def _boom_handler() -> None:
    raise RuntimeError("job-a-exploded")


@pytest.fixture(autouse=True)
def _allow_test_handlers(monkeypatch):
    """放行 tests.* 測試 handler（生產白名單僅 app.dp./app.et./app.dm.）。"""
    monkeypatch.setattr(
        scheduler_mod, "_ALLOWED_HANDLER_PREFIXES", scheduler_mod._ALLOWED_HANDLER_PREFIXES + ("tests.",)
    )


async def _logs(db, job_id):
    return list((await db.execute(select(DpScheduleLog).where(DpScheduleLog.job_id == job_id))).scalars().all())


async def test_cross_job_failure_isolation(db):
    """一 job 失敗（FAILED）不影響另一 job 執行（SUCCESS）；兩者各自獨立記錄（SC-011）。"""
    # SCHDP001（失敗）與 SCHET001（成功）皆為 #0 種子中存在之 job_id（滿足 LOG FK）
    failed = await run_and_log(db, "SCHDP001", f"{_HANDLER_MOD}._boom_handler")
    succeeded = await run_and_log(db, "SCHET001", f"{_HANDLER_MOD}._ok_handler")

    assert failed == "FAILED"
    assert succeeded == "SUCCESS"

    a_logs = await _logs(db, "SCHDP001")
    b_logs = await _logs(db, "SCHET001")
    assert len(a_logs) == 1 and a_logs[0].status == "FAILED" and "job-a-exploded" in a_logs[0].error_msg
    # 關鍵：A 失敗後 B 仍成功執行並留下獨立歷程（隔離）
    assert len(b_logs) == 1 and b_logs[0].status == "SUCCESS" and b_logs[0].error_msg is None


async def test_skipped_logged_on_overlap(db):
    """前次未完成 → 本次跳過並寫 SKIPPED 歷程（不重複執行同一 job，SC-011）。"""
    await write_skipped_log(db, "SCHDP001")
    logs = await _logs(db, "SCHDP001")
    assert len(logs) == 1 and logs[0].status == "SKIPPED"


async def test_schdp001_dual_mandate_composed(db):
    """SCHDP001 每日作業雙職責同批生效：閒置帳號禁用 + 密碼到期提醒（SC-011 + 平台自持）。"""
    now = utcnow()
    svc = UsersService()

    # 職責①對象：閒置逾 90 日（120 日未登入）
    db.add(
        DpUser(
            user_id="idle_e2e",
            email="idle_e2e@x.com",
            pwd_hash="x",
            user_name="閒置者",
            status="ACTIVE",
            pwd_changed_date=now,
            last_login_date=now - timedelta(days=120),
            created_user="seed",
            created_date=now - timedelta(days=200),
            deleted=0,
        )
    )
    # 職責②對象：密碼將於窗內到期（pwd_changed 85 日前，EXPIRY 90 / REMIND 7 → 剩 5 日）
    db.add(
        DpUser(
            user_id="expiring_e2e",
            email="expiring_e2e@x.com",
            pwd_hash="x",
            user_name="將到期者",
            status="ACTIVE",
            pwd_changed_date=now - timedelta(days=85),
            last_login_date=now - timedelta(days=1),
            created_user="seed",
            created_date=now - timedelta(days=100),
            deleted=0,
        )
    )
    await db.flush()

    # 每日作業兩職責（daily_platform_job 依序呼叫的兩個核心）
    disabled = await svc.disable_idle_accounts(db)
    reminded = await svc.send_pwd_expiry_reminders(db)

    assert disabled >= 1 and reminded >= 1

    # 職責①：閒置者已禁用 + 稽核（func_name=DP-USERS、operator=SYSTEM）
    idle = await UsersRepository().get_by_id(db, "idle_e2e")
    assert idle.status == "DISABLED"
    audit = (
        await db.execute(
            select(DpAuditLog).where(DpAuditLog.func_name == "DP-USERS", DpAuditLog.target_id == "idle_e2e")
        )
    ).scalar_one()
    assert audit.created_user == "SYSTEM"

    # 職責②：將到期者收到 PWD_EXPIRY_REMIND（EMAIL_LOG PENDING）
    mail = (
        await db.execute(select(DpEmailLog).where(DpEmailLog.recipient == "expiring_e2e@x.com"))
    ).scalar_one()
    assert mail.template_code == "PWD_EXPIRY_REMIND" and mail.status == "PENDING"

    # 且將到期者「未」被誤禁用（兩職責對象互不干擾）
    expiring = await UsersRepository().get_by_id(db, "expiring_e2e")
    assert expiring.status == "ACTIVE"