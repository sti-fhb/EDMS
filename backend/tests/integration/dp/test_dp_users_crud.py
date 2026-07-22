"""US4 使用者管理整合測試：查詢 / 代建 / 停用（自我保護）/ 啟用 / 解鎖 / 基本資料 + 稽核。

多以 UsersService + 真實 DB 直測業務規則與稽核落地；另抽樣一條 HTTP 驗 router 接線與分頁回應。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser
from app.dp.users.schemas import UserCreate, UserUpdate
from app.dp.users.service import UsersService

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"
_OP = OperatorInfo(user_id="admin01")


@pytest.fixture
def et_stub():
    """註冊 ET grant_default_role stub，記錄被授權的 user_id。"""
    granted: list[str] = []

    async def _grant(_db, user_id):
        granted.append(user_id)

    module_provisioning_gate.register("ET", _grant)
    yield granted
    module_provisioning_gate.unregister("ET")


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


# ---- 代建帳號（AC2）----

async def test_create_user_builds_active_must_change_grants_and_audits(db, et_stub):
    svc = UsersService()
    resp = await svc.create_user(
        db, data=UserCreate(email="new@edms.local", user_name="新人", password=_GOOD_PWD), operator=_OP
    )

    user = (await db.execute(select(DpUser).where(DpUser.email == "new@edms.local"))).scalar_one()
    assert user.status == "ACTIVE"
    assert user.must_change_pwd is True  # 首次登入強制變更（FR-03）
    assert resp.user_id == user.user_id
    # 授 ET 學員（同 US2 規則）
    assert user.user_id in et_stub
    # 首筆密碼歷程
    seq = await AuthRepository().next_pwd_seq_no(db, user.user_id)
    assert seq == 2  # 已存在 seq=1 → 下一個為 2
    # 雙稽核（帳號 CREATE + 角色授予）
    assert await _count_audit(db, user.user_id, "CREATE") == 2


async def test_create_user_duplicate_email_rejected(db, et_stub):
    await _make_user(db, "u1", email="dup@edms.local")
    svc = UsersService()
    with pytest.raises(AppError) as exc:
        await svc.create_user(
            db, data=UserCreate(email="dup@edms.local", user_name="重複", password=_GOOD_PWD), operator=_OP
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "DP_USER_007"


# ---- 查詢（AC1）----

async def test_list_filters_by_keyword_and_status(db):
    await _make_user(db, "a1", email="alice@edms.local", name="Alice")
    await _make_user(db, "b1", email="bob@edms.local", name="Bob", status="DISABLED")
    await _make_user(db, "c1", email="carol@edms.local", name="Carol", locked_until=utcnow() + timedelta(minutes=30))
    svc = UsersService()

    # 關鍵字（Email 模糊）
    by_kw = await svc.list_users(db, keyword="alice", status=None, page=1, limit=20)
    assert by_kw["meta"]["total"] == 1 and by_kw["data"][0].email == "alice@edms.local"
    # 狀態：已停用
    disabled = await svc.list_users(db, keyword=None, status="disabled", page=1, limit=20)
    assert {u.user_id for u in disabled["data"]} == {"b1"}
    # 狀態：已鎖定（ACTIVE 且 locked_until > now）
    locked = await svc.list_users(db, keyword=None, status="locked", page=1, limit=20)
    assert {u.user_id for u in locked["data"]} == {"c1"}
    # 狀態：啟用中（排除鎖定 / 停用）
    active = await svc.list_users(db, keyword=None, status="active", page=1, limit=20)
    assert {u.user_id for u in active["data"]} == {"a1"}


# ---- 停用 / 啟用（AC3/4/7）----

async def test_disable_then_enable_with_audit(db):
    await _make_user(db, "t1")
    svc = UsersService()

    await svc.set_status(db, user_id="t1", action="disable", operator=_OP)
    assert (await svc._repo.get_by_id(db, "t1")).status == "DISABLED"

    await svc.set_status(db, user_id="t1", action="enable", operator=_OP)
    assert (await svc._repo.get_by_id(db, "t1")).status == "ACTIVE"
    # 停用 + 啟用各一筆 UPDATE 稽核
    assert await _count_audit(db, "t1", "UPDATE") == 2


async def test_disable_self_blocked(db):
    await _make_user(db, "admin01")
    svc = UsersService()
    with pytest.raises(AppError) as exc:
        await svc.set_status(db, user_id="admin01", action="disable", operator=_OP)
    assert exc.value.status_code == 403
    assert exc.value.error_code == "DP_USER_006"


# ---- 解鎖（AC5）----

async def test_unlock_resets_fail_count_and_locked(db):
    await _make_user(db, "lk", locked_until=utcnow() + timedelta(minutes=30))
    svc = UsersService()
    await svc.unlock(db, user_id="lk", operator=_OP)
    user = await svc._repo.get_by_id(db, "lk")
    assert user.login_fail_count == 0
    assert user.locked_until is None
    assert await _count_audit(db, "lk", "UPDATE") == 1


# ---- 基本資料（AC6）----

async def test_update_basic_direct_and_email_unique(db):
    await _make_user(db, "e1", email="e1@edms.local", name="舊名")
    await _make_user(db, "e2", email="e2@edms.local")
    svc = UsersService()

    # 直接更新姓名 / Email
    await svc.update_basic(db, user_id="e1", data=UserUpdate(user_name="新名", email="e1new@edms.local"), operator=_OP)
    user = await svc._repo.get_by_id(db, "e1")
    assert user.user_name == "新名" and user.email == "e1new@edms.local"
    assert await _count_audit(db, "e1", "UPDATE") == 1

    # Email 撞他人 → 409
    with pytest.raises(AppError) as exc:
        await svc.update_basic(db, user_id="e1", data=UserUpdate(user_name="新名", email="e2@edms.local"), operator=_OP)
    assert exc.value.error_code == "DP_USER_007"


# ---- 不存在 ----

async def test_status_on_missing_user_404(db):
    svc = UsersService()
    with pytest.raises(AppError) as exc:
        await svc.set_status(db, user_id="ghost", action="enable", operator=_OP)
    assert exc.value.status_code == 404
    assert exc.value.error_code == "DP_USER_008"


# ---- HTTP 接線抽樣（分頁回應 + 認證）----

async def test_list_users_http_paged(db, client):
    await _make_user(db, "admin01")  # operator 本人（get_jwt_payload 查得到）
    await _make_user(db, "x1", email="x1@edms.local")
    token = create_access_token(sub="admin01", ttl_minutes=15)

    resp = await client.get("/api/dp/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and "meta" in body
    assert body["meta"]["total"] >= 2
    # 回應不外露密碼欄位
    assert all("pwd_hash" not in row for row in body["data"])
