"""US4 帳號啟用整合測試（#67）：受邀者持邀請 token 自設密碼 → 建 DP_USER + 啟用副作用。

啟用副作用（建 DP_USER(ACTIVE) + 首筆 PWD_HIST + 授 ET 學員 + 雙稽核 + 刪 pending）與 US2 verify
共用 `activate_pending_account`；此檔驗 US4 專屬路徑：僅 ADMIN_INVITE token、密碼由使用者當場設定。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.activate_service import ActivateAccountService
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.dp.user.verify_service import VerifyService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_GOOD_PWD = "Abcd1234"


@pytest.fixture
def et_stub():
    """註冊 ET grant_default_role stub，記錄被授權的 user_id。"""
    granted: list[str] = []

    async def _grant(_db, user_id):
        granted.append(user_id)

    module_provisioning_gate.register("ET", _grant)
    yield granted
    module_provisioning_gate.unregister("ET")


async def _make_invite(db, *, token="invite-tok", email="invitee@edms.local", name="受邀者", ttl_min=30):
    """建立一筆 ADMIN_INVITE 待啟用列（pwd_hash 為 None）。"""
    now = utcnow()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=hash_token(token),
        email=email,
        user_name=name,
        pwd_hash=None,
        expires_date=now + timedelta(minutes=ttl_min),
        now=now,
        kind="ADMIN_INVITE",
        res_id="inv-res-1",
        operator_id="admin01",
    )


async def test_activate_builds_user_grants_and_deletes_pending(db, et_stub):
    await _make_invite(db)
    await ActivateAccountService().activate(db, token="invite-tok", new_password=_GOOD_PWD, confirm_password=_GOOD_PWD)

    user = (await db.execute(select(DpUser).where(DpUser.email == "invitee@edms.local"))).scalar_one()
    assert user.status == "ACTIVE"
    assert user.must_change_pwd is False  # 使用者自設密碼，無須強制變更
    # 授 ET 學員
    assert user.user_id in et_stub
    # 首筆密碼歷程（下一個 seq 為 2）
    assert await AuthRepository().next_pwd_seq_no(db, user.user_id) == 2
    # 雙稽核（建帳號 + 授角色）
    cnt = (
        await db.execute(select(func.count()).select_from(DpAuditLog).where(DpAuditLog.target_id == user.user_id))
    ).scalar_one()
    assert cnt == 2
    # pending 已消費
    assert await AuthRepository().get_pending_by_email(db, "invitee@edms.local") is None


async def test_activate_invalid_token(db, et_stub):
    with pytest.raises(AppError) as exc:
        await ActivateAccountService().activate(db, token="nope", new_password=_GOOD_PWD, confirm_password=_GOOD_PWD)
    assert exc.value.status_code == 400
    assert exc.value.error_code == "DP_USER_003"


async def test_activate_rejects_self_register_token(db, et_stub):
    # 自助註冊 token（SELF_REGISTER）不得走啟用端點 → 視為無效
    now = utcnow()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=hash_token("self-tok"),
        email="self@edms.local",
        user_name="自助",
        pwd_hash="x",
        expires_date=now + timedelta(minutes=30),
        now=now,
    )
    with pytest.raises(AppError) as exc:
        await ActivateAccountService().activate(
            db, token="self-tok", new_password=_GOOD_PWD, confirm_password=_GOOD_PWD
        )
    assert exc.value.error_code == "DP_USER_003"


async def test_activate_expired_token(db, et_stub):
    await _make_invite(db, token="old-tok", ttl_min=-1)  # 已逾期
    with pytest.raises(AppError) as exc:
        await ActivateAccountService().activate(db, token="old-tok", new_password=_GOOD_PWD, confirm_password=_GOOD_PWD)
    assert exc.value.status_code == 400
    assert exc.value.error_code == "DP_USER_004"


async def test_verify_email_rejects_admin_invite_token(db, et_stub):
    # 反向守衛（安全 LOW-3）：管理者邀請 token 丟到 /verify-email 端點應被拒（DP_USER_003），
    # 不靠 DP_USER.PWD_HASH NOT NULL 約束兜底
    await _make_invite(db, token="inv-for-verify")
    with pytest.raises(AppError) as exc:
        await VerifyService().verify(db, token="inv-for-verify")
    assert exc.value.status_code == 400
    assert exc.value.error_code == "DP_USER_003"
    # pending 未被消費（交易語意）
    assert await AuthRepository().get_pending_by_email(db, "invitee@edms.local") is not None


async def test_activate_password_mismatch(db, et_stub):
    await _make_invite(db, token="mm-tok")
    with pytest.raises(AppError) as exc:
        await ActivateAccountService().activate(
            db, token="mm-tok", new_password=_GOOD_PWD, confirm_password="Different1"
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_USER_002"


async def test_activate_account_endpoint(client, db, et_stub):
    """/api/activate-account 端點（HTTP 層接線）：有效邀請 token + 合規密碼 → 200 + 建立 DP_USER。"""
    await _make_invite(db, token="http-tok")
    r = await client.post(
        "/api/activate-account",
        json={"token": "http-tok", "new_password": _GOOD_PWD, "confirm_password": _GOOD_PWD},
    )
    assert r.status_code == 200
    assert "message" in r.json()
    assert (
        await db.execute(select(DpUser).where(DpUser.email == "invitee@edms.local"))
    ).scalar_one_or_none() is not None
