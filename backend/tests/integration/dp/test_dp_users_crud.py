"""US4 使用者管理整合測試（#67 邀請流程）：查詢 / 建立邀請 / 待啟用清單 / 重寄 / 取消 / 停用啟用解鎖 / 改姓名 + 稽核。

多以 UsersService + 真實 DB 直測業務規則與稽核落地；另抽樣一條 HTTP 驗 router 接線與分頁回應。
建立 / 重寄邀請注入假 NotifyService（不實際寫 outbox），只驗「有無寄、寄哪個範本」。
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.activate_service import ActivateAccountService
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.dp.users.models import DpUser
from app.dp.users.schemas import UserCreate, UserUpdate
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_OP = OperatorInfo(user_id="admin01")


class _FakeNotify:
    """假發信服務：記錄每次 send_email 的收件人 / 範本 / 參數，不實際寫 outbox。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def send_email(self, _db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients, "template_code": template_code, "params": params})


def _svc(notify=None) -> UsersService:
    return UsersService(notify=notify or _FakeNotify())


async def _make_user(db, user_id, *, email=None, status="ACTIVE", locked_until=None, name="測試員"):
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email or f"{user_id}@edms.local",
        pwd_hash="x",
        user_name=name,
        status=status,
        login_fail_count=5 if locked_until else 0,
        locked_until=locked_until,
        pwd_changed_date=now,
        created_user="seed",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


async def _count_audit(db, target_id, action_type=None):
    stmt = select(func.count()).select_from(DpAuditLog).where(DpAuditLog.target_id == target_id)
    if action_type:
        stmt = stmt.where(DpAuditLog.action_type == action_type)
    return (await db.execute(stmt)).scalar_one()


async def _latest_audit(db, target_id):
    """取該 target 最新一筆稽核列（before/after 為 JSON 字串，呼叫端自行 json.loads）。"""
    stmt = select(DpAuditLog).where(DpAuditLog.target_id == target_id).order_by(DpAuditLog.log_id.desc()).limit(1)
    return (await db.execute(stmt)).scalars().first()


# ---- 建立邀請（AC2）----


async def test_create_invite_writes_pending_no_user_sends_and_audits(db):
    notify = _FakeNotify()
    await _svc(notify).create_user(db, data=UserCreate(email="new@edms.local", user_name="新人"), operator=_OP)

    # 不建 DP_USER
    cnt = (
        await db.execute(select(func.count()).select_from(DpUser).where(DpUser.email == "new@edms.local"))
    ).scalar_one()
    assert cnt == 0
    # 寫 pending：ADMIN_INVITE、pwd_hash 為 None、有 res_id
    pending = await AuthRepository().get_pending_by_email(db, "new@edms.local")
    assert pending is not None
    assert pending.kind == "ADMIN_INVITE"
    assert pending.pwd_hash is None
    assert pending.res_id
    # 寄邀請信（ACCOUNT_INVITE + activate_link）
    assert len(notify.calls) == 1
    assert notify.calls[0]["template_code"] == "ACCOUNT_INVITE"
    assert "activate_link" in notify.calls[0]["params"]
    # 稽核 CREATE（target = res_id）
    assert await _count_audit(db, pending.res_id, "CREATE") == 1


async def test_create_invite_duplicate_email_in_user_rejected(db):
    await _make_user(db, "u1", email="dup@edms.local")
    with pytest.raises(AppError) as exc:
        await _svc().create_user(db, data=UserCreate(email="dup@edms.local", user_name="重複"), operator=_OP)
    assert exc.value.status_code == 409
    assert exc.value.error_code == "DP_USER_007"


async def test_create_invite_on_active_pending_returns_409_guide_resend(db):
    """未逾期待啟用邀請重複建立 → 409 DP_USER_010（引導改用重寄，#111）；與『已啟用』的 007 區分。"""
    svc = _svc()
    await svc.create_user(db, data=UserCreate(email="p@edms.local", user_name="a"), operator=_OP)
    with pytest.raises(AppError) as exc:
        await svc.create_user(db, data=UserCreate(email="p@edms.local", user_name="b"), operator=_OP)
    assert exc.value.status_code == 409
    assert exc.value.error_code == "DP_USER_010"


async def test_create_invite_on_expired_pending_reinvites(db):
    """已逾期待啟用邀請重複建立 ＝ 重新邀請（#111）：沿用原 res_id、換新 token/效期、用新姓名、重寄、稽核。"""
    notify = _FakeNotify()
    svc = _svc(notify)
    # 塞一筆已逾期的 ADMIN_INVITE pending
    await AuthRepository().create_pending_registration(
        db,
        token_hash="oldhash",
        email="exp@edms.local",
        user_name="舊名",
        pwd_hash=None,
        expires_date=utcnow() - timedelta(minutes=1),
        now=utcnow(),
        kind="ADMIN_INVITE",
        res_id="oldres1",
        operator_id="admin01",
    )

    await svc.create_user(db, data=UserCreate(email="exp@edms.local", user_name="新名"), operator=_OP)

    pending = await AuthRepository().get_pending_by_email(db, "exp@edms.local")
    assert pending is not None
    assert pending.res_id == "oldres1"  # 沿用原 res_id（識別碼穩定）
    assert pending.token_hash != "oldhash"  # 舊 token 已作廢
    assert pending.expires_date > utcnow()  # 效期重設為未來
    assert pending.user_name == "新名"  # 用本次請求的姓名
    assert len(notify.calls) == 1  # 重寄 ACCOUNT_INVITE
    assert notify.calls[0]["template_code"] == "ACCOUNT_INVITE"
    # 稽核記 UPDATE（與同性質的 resend_invite 一致，非 CREATE），且帶被覆蓋掉的舊列快照
    assert await _count_audit(db, "oldres1", "UPDATE") == 1
    audit = await _latest_audit(db, "oldres1")
    before, after = json.loads(audit.before_value), json.loads(audit.after_value)
    assert before["user_name"] == "舊名"
    assert before["kind"] == "ADMIN_INVITE"
    assert after["user_name"] == "新名"
    assert after["expires_date"] > before["expires_date"]  # ISO 字串可直接比大小


@pytest.mark.parametrize("expired", [False, True], ids=["active", "expired"])
async def test_create_invite_on_self_register_pending_rejected(db, expired):
    """Email 正被**自助註冊**（SELF_REGISTER）佔用 → 409 DP_USER_007（#111）。

    不可回 DP_USER_010：該列不在邀請清單、res_id 為 NULL，管理者根本無可重寄對象；
    逾期亦不得走「重新邀請」覆蓋他人的自助註冊列（含其 pwd_hash）。
    """
    offset = -timedelta(minutes=1) if expired else timedelta(minutes=30)
    await AuthRepository().create_pending_registration(
        db,
        token_hash="selfhash",
        email="selfreg@edms.local",
        user_name="自助",
        pwd_hash="x",
        expires_date=utcnow() + offset,
        now=utcnow(),
    )

    with pytest.raises(AppError) as exc:
        await _svc().create_user(db, data=UserCreate(email="selfreg@edms.local", user_name="管建"), operator=_OP)

    assert exc.value.status_code == 409
    assert exc.value.error_code == "DP_USER_007"
    # 他人的自助註冊列未被覆蓋
    pending = await AuthRepository().get_pending_by_email(db, "selfreg@edms.local")
    assert pending.kind == "SELF_REGISTER"
    assert pending.token_hash == "selfhash"


async def test_reinvite_invalidates_old_invite_token(db):
    """重新邀請後**舊邀請連結必須失效**（#111）：以舊明文 token 啟用 → 400 DP_USER_003（查無此 token）。"""
    svc = _svc()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=hash_token("old-plain-token"),
        email="tok@edms.local",
        user_name="舊名",
        pwd_hash=None,
        expires_date=utcnow() - timedelta(minutes=1),
        now=utcnow(),
        kind="ADMIN_INVITE",
        res_id="oldres2",
        operator_id="admin01",
    )

    await svc.create_user(db, data=UserCreate(email="tok@edms.local", user_name="新名"), operator=_OP)

    with pytest.raises(AppError) as exc:
        await ActivateAccountService().activate(
            db, token="old-plain-token", new_password="Abcd1234", confirm_password="Abcd1234"
        )
    assert exc.value.status_code == 400
    assert exc.value.error_code == "DP_USER_003"


# ---- 待啟用邀請清單 / 重寄 / 取消（AC10）----


async def test_list_invites_only_admin_invite(db):
    svc = _svc()
    await svc.create_user(db, data=UserCreate(email="inv@edms.local", user_name="邀"), operator=_OP)
    # 另塞一筆自助註冊 pending（SELF_REGISTER，不應出現在邀請清單）
    await AuthRepository().create_pending_registration(
        db,
        token_hash="selfhash",
        email="self@edms.local",
        user_name="自助",
        pwd_hash="x",
        expires_date=utcnow() + timedelta(minutes=30),
        now=utcnow(),
    )
    res = await svc.list_invites(db, keyword=None, page=1, limit=20)
    emails = {r.email for r in res["data"]}
    assert "inv@edms.local" in emails
    assert "self@edms.local" not in emails


async def test_resend_invite_rotates_token_keeps_res_id_and_resends(db):
    notify = _FakeNotify()
    svc = _svc(notify)
    await svc.create_user(db, data=UserCreate(email="r@edms.local", user_name="R"), operator=_OP)
    pending = await AuthRepository().get_pending_by_email(db, "r@edms.local")
    old_hash, res_id = pending.token_hash, pending.res_id

    await svc.resend_invite(db, res_id=res_id, operator=_OP)

    new_pending = await AuthRepository().get_pending_by_email(db, "r@edms.local")
    assert new_pending.token_hash != old_hash  # 舊 token 已作廢
    assert new_pending.res_id == res_id  # res_id 不變（識別碼穩定）
    assert len(notify.calls) == 2  # 建立 + 重寄各一封


async def test_cancel_invite_deletes_pending(db):
    svc = _svc()
    await svc.create_user(db, data=UserCreate(email="c@edms.local", user_name="C"), operator=_OP)
    pending = await AuthRepository().get_pending_by_email(db, "c@edms.local")
    await svc.cancel_invite(db, res_id=pending.res_id, operator=_OP)
    assert await AuthRepository().get_pending_by_email(db, "c@edms.local") is None


async def test_resend_missing_invite_404(db):
    with pytest.raises(AppError) as exc:
        await _svc().resend_invite(db, res_id="ghost", operator=_OP)
    assert exc.value.status_code == 404
    assert exc.value.error_code == "DP_USER_009"


async def test_cancel_missing_invite_404(db):
    with pytest.raises(AppError) as exc:
        await _svc().cancel_invite(db, res_id="ghost", operator=_OP)
    assert exc.value.status_code == 404
    assert exc.value.error_code == "DP_USER_009"


# ---- 查詢（AC1）----


async def test_list_filters_by_keyword_and_status(db):
    await _make_user(db, "a1", email="alice@edms.local", name="Alice")
    await _make_user(db, "b1", email="bob@edms.local", name="Bob", status="DISABLED")
    await _make_user(db, "c1", email="carol@edms.local", name="Carol", locked_until=utcnow() + timedelta(minutes=30))
    svc = _svc()

    by_kw = await svc.list_users(db, keyword="alice", status=None, page=1, limit=20)
    assert by_kw["meta"]["total"] == 1 and by_kw["data"][0].email == "alice@edms.local"
    disabled = await svc.list_users(db, keyword=None, status="disabled", page=1, limit=20)
    assert {u.user_id for u in disabled["data"]} == {"b1"}
    locked = await svc.list_users(db, keyword=None, status="locked", page=1, limit=20)
    assert {u.user_id for u in locked["data"]} == {"c1"}
    active = await svc.list_users(db, keyword=None, status="active", page=1, limit=20)
    assert {u.user_id for u in active["data"]} == {"a1"}


# ---- 停用 / 啟用（AC3/4/7）----


async def test_disable_then_enable_with_audit(db):
    await _make_user(db, "t1")
    svc = _svc()
    await svc.set_status(db, user_id="t1", action="disable", operator=_OP)
    assert (await svc._repo.get_by_id(db, "t1")).status == "DISABLED"
    await svc.set_status(db, user_id="t1", action="enable", operator=_OP)
    assert (await svc._repo.get_by_id(db, "t1")).status == "ACTIVE"
    assert await _count_audit(db, "t1", "UPDATE") == 2


async def test_disable_self_blocked(db):
    await _make_user(db, "admin01")
    with pytest.raises(AppError) as exc:
        await _svc().set_status(db, user_id="admin01", action="disable", operator=_OP)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_USER_006"


# ---- 解鎖（AC5）----


async def test_unlock_resets_fail_count_and_locked(db):
    await _make_user(db, "lk", locked_until=utcnow() + timedelta(minutes=30))
    svc = _svc()
    await svc.unlock(db, user_id="lk", operator=_OP)
    user = await svc._repo.get_by_id(db, "lk")
    assert user.login_fail_count == 0
    assert user.locked_until is None
    assert await _count_audit(db, "lk", "UPDATE") == 1


# ---- 編輯：僅改姓名，Email 唯讀（AC6）----


async def test_update_only_name_email_unchanged(db):
    await _make_user(db, "e1", email="e1@edms.local", name="舊名")
    svc = _svc()
    await svc.update_basic(db, user_id="e1", data=UserUpdate(user_name="新名"), operator=_OP)
    user = await svc._repo.get_by_id(db, "e1")
    assert user.user_name == "新名"
    assert user.email == "e1@edms.local"  # Email 不因編輯而變
    assert await _count_audit(db, "e1", "UPDATE") == 1


# ---- 不存在 ----


async def test_status_on_missing_user_404(db):
    with pytest.raises(AppError) as exc:
        await _svc().set_status(db, user_id="ghost", action="enable", operator=_OP)
    assert exc.value.status_code == 404
    assert exc.value.error_code == "DP_USER_008"


# ---- HTTP 接線抽樣（分頁回應 + 認證）----


async def test_list_users_http_paged(db, client):
    await _make_user(db, "admin01")
    await _make_user(db, "x1", email="x1@edms.local")
    token = create_access_token(sub="admin01", ttl_minutes=15)

    resp = await client.get("/api/dp/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and "meta" in body
    assert body["meta"]["total"] >= 2
    assert all("pwd_hash" not in row for row in body["data"])
