"""US11 SCHDP001 平台每日作業整合測試（handler / UsersService）。

直測 `UsersService.disable_idle_accounts` / `send_pwd_expiry_reminders`（接收 db、逐筆 commit 容錯）
與第④批 `redaction.redact_expired_failed_mails`（#50）。
涵蓋 AC6①（閒置禁用 + 稽核 func_name=DP-USERS + null→CREATED_DATE 基準）/ AC6②（到期提醒→EMAIL_LOG PENDING）。
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.notify.models import DpEmailLog
from app.dp.notify.redaction import REDACTED_BODY, redact_expired_failed_mails
from app.dp.user.models import DpPendingRegistration
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser
from app.dp.users.repository import UsersRepository
from app.dp.users.service import UsersService
from app.services import NotifyService

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


async def test_閒置禁用單筆失敗不中止整批(db, monkeypatch):
    """逐筆容錯必須真的容錯：第一筆失敗後，其餘仍要被處理完。

    原本會整批中止，而且失敗得很隱蔽——`rollback()` 會使**掃描階段取得的 ORM 實體全數
    過期**，接著那行 `logger.exception(..., user.user_id)` 的屬性存取觸發 lazy refresh，
    在 async 下沒有 greenlet context 就拋 `MissingGreenlet`。

    也就是說：爆掉的正是那行「告訴你哪一筆失敗」的 log，於是既沒有錯誤歸因、後面的
    帳號也全部沒被處理，而排程紀錄上只會看到一個籠統的失敗。

    這裡固定讓**第一個被處理到的**失敗（不假設掃描順序），第二筆必須照常完成。
    """
    now = utcnow()
    await _seed_user(db, user_id="idle_a", email="idle_a@x.com", last_login=now - timedelta(days=120))
    await _seed_user(db, user_id="idle_b", email="idle_b@x.com", last_login=now - timedelta(days=120))
    await db.commit()

    original = UsersRepository.disable_if_still_idle
    calls = {"n": 0}

    async def flaky(self, db_, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("模擬單筆失敗")
        return await original(self, db_, **kwargs)

    monkeypatch.setattr(UsersRepository, "disable_if_still_idle", flaky)

    disabled = await _service.disable_idle_accounts(db)

    assert calls["n"] == 2, "第一筆失敗後就沒再處理第二筆——整批被中止了"
    assert disabled == 1


def _lock_timeout() -> Exception:
    """等稽核鎖逾時：55P03 的 DBAPIError。

    ⚠️ 正式環境的 `orig` 是 SQLAlchemy asyncpg 轉接層包過的例外（`sqlstate` 由轉接層帶上），這裡直接用
    asyncpg 例外；兩者都有 `sqlstate`，判斷式只讀它。真實鎖逾時的形狀由 `test_core_db_busy_timeouts.py` 守門。
    """
    import asyncpg.exceptions as pg_exc
    from sqlalchemy.exc import DBAPIError

    return DBAPIError.instance(
        statement="SELECT pg_advisory_xact_lock($1)",
        params=(1,),
        orig=pg_exc.LockNotAvailableError("canceling statement due to lock timeout"),
        dbapi_base_err=Exception,
    )


async def _audit_rows(db, target_id: str) -> int:
    rows = await db.scalars(select(DpAuditLog).where(DpAuditLog.target_id == target_id))
    return len(rows.all())


async def test_閒置禁用遇稽核鎖逾時_原地重試成功(db, monkeypatch):
    """#905 B5：等稽核鎖超過 `DB_AUDIT_LOCK_TIMEOUT_MS` 就放棄該筆的話，那個帳號要等到隔天的排程才停用。
    鎖逾時是暫時性的，原地重試。"""
    now = utcnow()
    await _seed_user(db, user_id="lock_a", email="lock_a@x.com", last_login=now - timedelta(days=120))
    await db.commit()

    from app.dp.audit.service import AuditLogService

    original = AuditLogService.log_action
    calls = {"n": 0}

    async def busy_once(self, db_, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _lock_timeout()
        return await original(self, db_, **kwargs)

    monkeypatch.setattr(AuditLogService, "log_action", busy_once)

    disabled = await _service.disable_idle_accounts(db)

    assert calls["n"] == 2, "鎖逾時後應重試同一筆"
    assert disabled == 1
    assert (await _get(db, "lock_a")).status == "DISABLED"
    assert await _audit_rows(db, "lock_a") == 1, "重試成功只留一筆稽核（第一次已 rollback）"


async def test_閒置禁用持續鎖逾時_重試有上限且不擋其餘(db, monkeypatch):
    """鎖一直拿不到時不能無限重試（每次等 10 秒）；放棄該筆後照常處理下一筆。"""
    now = utcnow()
    await _seed_user(db, user_id="lock_b", email="lock_b@x.com", last_login=now - timedelta(days=120))
    await _seed_user(db, user_id="lock_c", email="lock_c@x.com", last_login=now - timedelta(days=130))
    await db.commit()

    from app.dp.audit.service import AuditLogService

    original = AuditLogService.log_action
    attempts: dict[str, int] = {}

    async def busy_for_b(self, db_, **kwargs):
        target = kwargs["target_id"]
        attempts[target] = attempts.get(target, 0) + 1
        if target == "lock_b":
            raise _lock_timeout()
        return await original(self, db_, **kwargs)

    monkeypatch.setattr(AuditLogService, "log_action", busy_for_b)

    disabled = await _service.disable_idle_accounts(db)

    assert attempts == {"lock_b": 3, "lock_c": 1}, "鎖逾時共試 3 次（原本 1 次 + 重試 2 次）"
    assert disabled == 1
    assert (await _get(db, "lock_b")).status == "ACTIVE"
    assert (await _get(db, "lock_c")).status == "DISABLED"


async def test_閒置禁用非鎖逾時的錯誤不重試(db, monkeypatch):
    """只有鎖逾時是暫時性的；其他錯誤（含查詢逾時 57014）重試也只是再等一次，照舊記失敗、隔天補做。"""
    now = utcnow()
    await _seed_user(db, user_id="lock_d", email="lock_d@x.com", last_login=now - timedelta(days=120))
    await db.commit()

    import asyncpg.exceptions as pg_exc
    from sqlalchemy.exc import DBAPIError

    from app.dp.audit.service import AuditLogService

    calls = {"n": 0}

    async def query_canceled(self, db_, **kwargs):
        calls["n"] += 1
        raise DBAPIError.instance(
            statement="SELECT 1",
            params=(),
            orig=pg_exc.QueryCanceledError("canceling statement due to statement timeout"),
            dbapi_base_err=Exception,
        )

    monkeypatch.setattr(AuditLogService, "log_action", query_canceled)

    assert await _service.disable_idle_accounts(db) == 0
    assert calls["n"] == 1


async def test_重試前剛登入的帳號不被停用(db, monkeypatch):
    """第一次等鎖逾時、rollback 之後，該使用者剛好登入（另一個交易 commit）：重試時必須依寫入當下的狀態
    重新判定，不可把剛登入的人停用、也不可寫出 before 值不實的稽核（#905 B5 security review L1）。"""
    from sqlalchemy import update

    from app.dp.audit.service import AuditLogService

    now = utcnow()
    await _seed_user(db, user_id="lock_e", email="lock_e@x.com", last_login=now - timedelta(days=120))
    await db.commit()

    original_audit = AuditLogService.log_action
    calls = {"n": 0}

    async def busy_once(self, db_, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _lock_timeout()
        return await original_audit(self, db_, **kwargs)

    original_rollback = db.rollback

    async def rollback_then_login() -> None:
        await original_rollback()
        if calls["n"] == 1:  # 第一次失敗回滾後，模擬使用者登入成功並 commit
            await db.execute(
                update(DpUser)
                .where(DpUser.user_id == "lock_e")
                .values(last_login_date=utcnow())
                .execution_options(synchronize_session=False)
            )
            await db.commit()

    monkeypatch.setattr(AuditLogService, "log_action", busy_once)
    monkeypatch.setattr(db, "rollback", rollback_then_login)

    disabled = await _service.disable_idle_accounts(db)

    assert calls["n"] == 1, "重試時已不符合閒置條件，不該再寫稽核"
    assert disabled == 0
    assert (await _get(db, "lock_e")).status == "ACTIVE"
    assert await _audit_rows(db, "lock_e") == 0


async def test_閒置禁用有失敗時彙總記一筆_WARNING(db, monkeypatch, caplog):
    """逐筆的 ERROR 散落各處；有失敗時另記一筆彙總，安全控制連續幾天靜默失效才看得到（security review M1）。"""
    import logging

    now = utcnow()
    await _seed_user(db, user_id="lock_f", email="lock_f@x.com", last_login=now - timedelta(days=120))
    await db.commit()

    async def always_fail(self, db_, **kwargs):
        raise RuntimeError("模擬單筆失敗")

    monkeypatch.setattr(UsersRepository, "disable_if_still_idle", always_fail)

    with caplog.at_level(logging.WARNING, logger="app.dp.users.service"):
        assert await _service.disable_idle_accounts(db) == 0

    summary = [r for r in caplog.records if r.levelno == logging.WARNING and "閒置禁用失敗 1 筆" in r.getMessage()]
    assert len(summary) == 1


async def test_密碼到期提醒單筆失敗不中止整批(db, monkeypatch):
    """同上，但這支更嚴重：下一圈的 `user.pwd_changed_date` 在 `try` **之外**。

    `disable_idle_accounts` 的屬性存取還在 try 內（至少會被自己的 except 接住），而這支
    迴圈開頭就讀 `user.pwd_changed_date` 算到期日——rollback 之後那行直接拋出，連本函式
    的 except 都接不到，例外會一路穿到排程外層。
    """
    now = utcnow()
    pwd_changed = now - timedelta(days=85)  # 90 天到期、提前 7 天提醒 → 落在視窗內
    await _seed_user(db, user_id="exp_a", email="exp_a@x.com", pwd_changed=pwd_changed)
    await _seed_user(db, user_id="exp_b", email="exp_b@x.com", pwd_changed=pwd_changed)
    await db.commit()

    original = NotifyService.send_email
    calls = {"n": 0}

    async def flaky(self, db_, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("模擬單筆寄信失敗")
        return await original(self, db_, **kwargs)

    monkeypatch.setattr(NotifyService, "send_email", flaky)

    sent = await _service.send_pwd_expiry_reminders(db)

    assert calls["n"] == 2, "第一筆失敗後就沒再處理第二筆——整批被中止了"
    assert sent == 1


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


async def test_到期日以台灣時間呈現(db):
    """信裡的到期日須為**台灣時間**的日期，不是 asyncpg 回傳物件的 UTC 日期（#513 第 1 項）。

    ⚠️ **時點刻意取「UTC 23:00 ＝ 台灣隔天 07:00」**：兩者日期不同，修法有沒有生效才分得出來。
    若取中午的時點，UTC 與台灣同日，`strftime` 與 `format_taipei_date` 都會給出同一個字串——
    改與不改都會過，這條測試就白寫了。

    此欄位在本 issue 之前**無任何測試覆蓋**（既有測試只斷言信有寄出），所以錯了一直是綠的。
    """
    # 到期日落在提醒窗內（3 天後），且 UTC 時刻為 23:00
    expiry_at = (utcnow() + timedelta(days=3)).replace(hour=23, minute=0, second=0, microsecond=0)
    await _seed_user(db, user_id="exptz", email="exptz@x.com", pwd_changed=expiry_at - timedelta(days=90))

    sent = await _service.send_pwd_expiry_reminders(db)

    assert sent == 1
    body = (await _reminder_logs(db))[0].body
    taipei_date = expiry_at.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    utc_date = expiry_at.strftime("%Y-%m-%d")
    assert taipei_date != utc_date, "時點設計失誤：兩者同日則本測試無鑑別力"
    assert taipei_date in body
    assert utc_date not in body  # 修正前出現的是這個（早一天）


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
    # **只清 SELF_REGISTER**：逾期的管理者邀請仍是 UI 物件——build_invite_list_stmt 沒有效期條件，
    # 逾期邀請會列在「待啟用邀請」頁籤並顯示「已逾期」，管理者可直接按「重寄邀請」，那正是
    # spec_us4.md AC10 定義的情境。清掉會讓邀請靜默消失（週五寄的，管理者週一就找不到）、
    # resend_invite / cancel_invite 對舊 invite_id 回 404，且邀請的稽核鏈以無終結事件收尾。
    # 自助註冊列則在任何 UI 上都看不見，那才是需要排程清的一類。
    assert "old-invite@edms.local" in remaining
    assert purged == 1


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


# ── ④ 遮罩逾連結時效之寄送失敗信件（#50 SA 2026-11-02 裁示 2）──────────────


async def _seed_email_log(db, *, module, code, status, body, age):
    row = DpEmailLog(
        module=module,
        template_code=code,
        caller_module=module,
        recipient=f"{module}-{code}-{status}-{age.total_seconds():.0f}-{len(body)}@edms.local",
        subject="s",
        body=body,
        status=status,
        retry_count=0,
        created_user="SYSTEM",
        created_date=utcnow() - age,
    )
    db.add(row)
    await db.flush()
    return row.message_id


async def test_redact_expired_failed_mails_only_touches_failed_link_mails_past_ttl(db):
    """只遮 (DP, 四支一次性連結信) 且 FAILED 且建立已逾時效者；其餘一律保留原狀。

    「逾時」取 3 小時、「未逾時」取 1 分鐘：時效參數值域為 1~120 分（param_rules），
    兩者在任何合法參數值下都分得開，測試不依賴種子參數值。
    """
    link = "請點擊 https://edms.example/x?token=PLAINTEXT"
    old, fresh = timedelta(hours=3), timedelta(minutes=1)
    ids = {
        "pwd_old": await _seed_email_log(db, module="DP", code="PWD_RESET", status="FAILED", body=link, age=old),
        "invite_old": await _seed_email_log(
            db, module="DP", code="ACCOUNT_INVITE", status="FAILED", body=link, age=old
        ),
        "verify_fresh": await _seed_email_log(
            db, module="DP", code="ACCOUNT_VERIFY", status="FAILED", body=link, age=fresh
        ),
        "render_failed": await _seed_email_log(db, module="DP", code="PWD_RESET", status="FAILED", body="", age=old),
        "pending_old": await _seed_email_log(db, module="DP", code="PWD_RESET", status="PENDING", body=link, age=old),
        "et_same_code": await _seed_email_log(
            db, module="ET", code="ACCOUNT_INVITE", status="FAILED", body=link, age=old
        ),
        "no_link_tpl": await _seed_email_log(
            db, module="DP", code="PWD_EXPIRY_REMIND", status="FAILED", body=link, age=old
        ),
    }

    redacted = await redact_expired_failed_mails(db)

    db.expire_all()
    rows = {
        r.message_id: r
        for r in (await db.execute(select(DpEmailLog).where(DpEmailLog.message_id.in_(ids.values())))).scalars()
    }
    body = {k: rows[v].body for k, v in ids.items()}
    # 先斷言 STATUS 未被動到，再看 BODY——遮罩不得改狀態
    assert {k for k, v in ids.items() if rows[v].status != "FAILED"} == {"pending_old"}
    assert body["pwd_old"] == REDACTED_BODY
    assert body["invite_old"] == REDACTED_BODY
    assert rows[ids["pwd_old"]].updated_user == "SYSTEM"
    assert body["verify_fresh"] == link  # 連結可能仍有效、尚未逾時
    assert body["render_failed"] == ""  # 渲染失敗列維持空 BODY，不偽裝成「曾含連結」
    assert body["pending_old"] == link  # PENDING 仍需原文重試
    assert body["et_same_code"] == link  # 以 (MODULE, TEMPLATE_CODE) 為鍵
    assert body["no_link_tpl"] == link  # 不含一次性連結的範本不在範圍
    assert redacted == 2

    # 每日重跑：已遮罩列不再改寫
    assert await redact_expired_failed_mails(db) == 0
