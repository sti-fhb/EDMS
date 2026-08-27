"""US11 SCHDP001 平台每日作業整合測試（handler / UsersService）。

直測 `UsersService.disable_idle_accounts` / `send_pwd_expiry_reminders`（接收 db、逐筆 commit 容錯）。
涵蓋 AC6①（閒置禁用 + 稽核 func_name=DP-USERS + null→CREATED_DATE 基準）/ AC6②（到期提醒→EMAIL_LOG PENDING）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.models import DpPendingRegistration
from app.dp.user.repository import AuthRepository
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.dp.users.repository import UsersRepository
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_service = UsersService()


async def _seed_user(db, *, user_id, email, last_login=None, pwd_changed=None, created=None, status="ACTIVE"):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash="x",
            user_name=f"U{user_id}",
            status=status,
            pwd_changed_date=pwd_changed or now,
            last_login_date=last_login,
            created_user="seed",
            created_date=created or now,
            deleted=0,
        )
    )
    await db.flush()


async def _get(db, user_id):
    return await UsersRepository().get_by_id(db, user_id)


# ── AC6① 閒置禁用 ─────────────────────────────────────────────────────────


async def test_disables_idle_over_threshold(db):
    """閒置逾 90 日（LAST_LOGIN_DATE 為基準）之 ACTIVE 帳號 → DISABLED + 稽核 func_name=DP-USERS。"""
    now = utcnow()
    await _seed_user(db, user_id="idle1", email="idle1@x.com", last_login=now - timedelta(days=120))

    disabled = await _service.disable_idle_accounts(db)

    assert disabled == 1
    assert (await _get(db, "idle1")).status == "DISABLED"
    audits = (
        (
            await db.execute(
                select(DpAuditLog).where(DpAuditLog.func_name == "DP-USERS", DpAuditLog.target_id == "idle1")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].created_user == "SYSTEM" and audits[0].action_type == "UPDATE"


async def test_idle_null_last_login_uses_created_date(db):
    """AC6①：從未登入（LAST_LOGIN_DATE=null）以 CREATED_DATE 為基準——建立逾 90 日 → 禁用。"""
    now = utcnow()
    await _seed_user(db, user_id="never1", email="never1@x.com", last_login=None, created=now - timedelta(days=120))

    disabled = await _service.disable_idle_accounts(db)

    assert disabled == 1
    assert (await _get(db, "never1")).status == "DISABLED"


async def test_recent_login_not_disabled(db):
    """近期登入者不禁用。"""
    now = utcnow()
    await _seed_user(db, user_id="active1", email="active1@x.com", last_login=now - timedelta(days=10))

    disabled = await _service.disable_idle_accounts(db)

    assert disabled == 0
    assert (await _get(db, "active1")).status == "ACTIVE"


async def test_disabled_account_skipped(db):
    """已停用帳號不重複處理。"""
    now = utcnow()
    await _seed_user(db, user_id="dis1", email="dis1@x.com", last_login=now - timedelta(days=120), status="DISABLED")

    assert await _service.disable_idle_accounts(db) == 0


# ── AC6② 密碼到期提醒 ─────────────────────────────────────────────────────


async def _reminder_logs(db):
    return list(
        (await db.execute(select(DpEmailLog).where(DpEmailLog.template_code == "PWD_EXPIRY_REMIND"))).scalars().all()
    )


async def test_sends_reminder_in_window(db):
    """AC6②：密碼將於提醒窗（到期前 7 天內）到期 → 寄 PWD_EXPIRY_REMIND、DP_EMAIL_LOG PENDING。"""
    now = utcnow()
    # 效期 90 天、提醒 7 天：密碼 85 天前改 → 5 天後到期，落在窗內
    await _seed_user(db, user_id="exp1", email="exp1@x.com", pwd_changed=now - timedelta(days=85))

    sent = await _service.send_pwd_expiry_reminders(db)

    assert sent == 1
    logs = await _reminder_logs(db)
    assert len(logs) == 1
    assert logs[0].recipient == "exp1@x.com" and logs[0].status == "PENDING"
    assert logs[0].module == "DP"


async def test_not_in_window_no_reminder(db):
    """密碼剛改（距到期遠）→ 不在窗內、不寄。"""
    now = utcnow()
    await _seed_user(db, user_id="fresh1", email="fresh1@x.com", pwd_changed=now - timedelta(days=10))

    assert await _service.send_pwd_expiry_reminders(db) == 0
    assert await _reminder_logs(db) == []


async def test_already_expired_no_reminder(db):
    """已過期（超過 90 天）→ 不在提醒窗（登入時強制變更處理），不寄。"""
    now = utcnow()
    await _seed_user(db, user_id="over1", email="over1@x.com", pwd_changed=now - timedelta(days=100))

    assert await _service.send_pwd_expiry_reminders(db) == 0


async def test_reminder_boundary_near_expiry(db):
    """邊界：89 天前變更（明日到期、距到期 1 天）→ 窗內，寄（避免恰 90 天之 now() 微秒漂移）。"""
    now = utcnow()
    await _seed_user(db, user_id="edge89", email="edge89@x.com", pwd_changed=now - timedelta(days=89))

    assert await _service.send_pwd_expiry_reminders(db) == 1


async def test_reminder_boundary_window_first_day(db):
    """邊界：剛好 83 天前變更（距到期 7 天，提醒窗第一天）→ 寄。"""
    now = utcnow()
    await _seed_user(db, user_id="edge83", email="edge83@x.com", pwd_changed=now - timedelta(days=83))

    assert await _service.send_pwd_expiry_reminders(db) == 1


async def test_reminder_just_outside_window(db):
    """邊界外：82 天前變更（距到期 8 天 > 提醒窗 7 天）→ 不寄。"""
    now = utcnow()
    await _seed_user(db, user_id="edge82", email="edge82@x.com", pwd_changed=now - timedelta(days=82))

    assert await _service.send_pwd_expiry_reminders(db) == 0


async def _seed_pending(db, *, email, expires_offset_hours, kind="SELF_REGISTER"):
    """塞一筆待驗證列，效期以「距現在幾小時」表示（負數＝已逾期）。"""
    now = utcnow()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=f"h-{email}",
        email=email,
        user_name="待驗證",
        pwd_hash=None,
        expires_date=now + timedelta(hours=expires_offset_hours),
        now=now,
        kind=kind,
        invite_id="inv-1" if kind == "ADMIN_INVITE" else None,
    )


async def test_purge_expired_pending_deletes_only_rows_expired_over_retention(db):
    """清理逾期待驗證列（#226）：**逾期滿 1 天**才刪；未滿 1 天與未逾期的都留。

    保留一天的理由：逾期的列本身已無用（token 不可用、#212 之後也不含密碼），但留一天讓當天的
    客服問題還查得到「這個 Email 前一天有人送過註冊」。

    在此之前 `models.py` 與 `data-model.md` 都寫著「逾期未驗證列由排程清理」，但 SCHDP001 只做
    閒置禁用與密碼到期提醒、不清這張表——那句話是空話，列會永久累積（而這張表匿名可寫）。
    """
    await _seed_pending(db, email="old-expired@edms.local", expires_offset_hours=-25)
    await _seed_pending(db, email="just-expired@edms.local", expires_offset_hours=-2)
    await _seed_pending(db, email="still-valid@edms.local", expires_offset_hours=1)
    await _seed_pending(db, email="old-invite@edms.local", expires_offset_hours=-25, kind="ADMIN_INVITE")

    purged = await _service.purge_expired_pending(db)

    remaining = {row.email for row in (await db.execute(select(DpPendingRegistration))).scalars().all()}
    assert "old-expired@edms.local" not in remaining
    assert "just-expired@edms.local" in remaining  # 逾期未滿保留期
    assert "still-valid@edms.local" in remaining  # 未逾期
    # 兩種 KIND 一視同仁：逾期的管理者邀請同樣已無用（重寄會產新 token，不依賴舊列）
    assert "old-invite@edms.local" not in remaining
    assert purged == 2


async def test_purge_expired_pending_writes_no_per_row_audit(db):
    """清理**不**逐列寫稽核，只回傳筆數供 handler 記 log（#226）。

    理由與 #225 的追溯決策一致：這張表**匿名可寫**（30 次/分/IP），逐列寫稽核等於讓任何人能往
    append-only、鏈式雜湊的 DP_AUDIT_LOG 灌列，把有意義的紀錄淹掉。而被清的列早已逾期、無業務
    意義——真正需要留痕的是「有人覆蓋了別人的列」（那條由 register_service / users.service 各自
    記 DELETE 稽核）。
    """
    before = len((await db.execute(select(DpAuditLog))).scalars().all())
    await _seed_pending(db, email="silent-purge@edms.local", expires_offset_hours=-48)

    assert await _service.purge_expired_pending(db) == 1

    after = len((await db.execute(select(DpAuditLog))).scalars().all())
    assert after == before
