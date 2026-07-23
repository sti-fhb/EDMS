"""US4 使用者管理整合測試（#67 邀請流程）：查詢 / 建立邀請 / 待啟用清單 / 重寄 / 取消 / 停用啟用解鎖 / 改姓名 + 稽核。

多以 UsersService + 真實 DB 直測業務規則與稽核落地；另抽樣一條 HTTP 驗 router 接線與分頁回應。
建立 / 重寄邀請注入假 NotifyService（不實際寫 outbox），只驗「有無寄、寄哪個範本」。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.repository import AuthRepository
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


async def test_create_invite_duplicate_email_in_pending_rejected(db):
    svc = _svc()
    await svc.create_user(db, data=UserCreate(email="p@edms.local", user_name="a"), operator=_OP)
    with pytest.raises(AppError) as exc:
        await svc.create_user(db, data=UserCreate(email="p@edms.local", user_name="b"), operator=_OP)
    assert exc.value.error_code == "DP_USER_007"


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
