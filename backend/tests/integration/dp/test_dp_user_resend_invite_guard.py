"""重寄驗證信不得吃掉管理者邀請（#137 問題 2）。

`ResendVerificationService.resend` 原本呼叫無條件的 `delete_pending_by_email`。
該路徑雖已先檢查 `kind == SELF_REGISTER`，但 check 到 delete 之間隔著兩次 DB 讀取與
token 產生；若該空窗內原自助註冊列被驗證消耗、管理者又對同 Email 發出邀請，
無條件刪除就會靜默吃掉那筆新邀請——與 #125 完全相同的 TOCTOU 形狀。

改用條件式刪除 `delete_pending_unless_active_invite` 後，邀請被保留，
後續插入撞 UNIQUE 轉為乾淨的 409（DP_USER_005），管理者的邀請不受影響。
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.user.kinds import KIND_ADMIN_INVITE, KIND_SELF_REGISTER
from app.dp.user.models import DpPendingRegistration
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.dp.user.verify_service import ResendVerificationService

pytestmark = pytest.mark.integration

_EMAIL = "invited@edms.local"


class _WindowRepo(AuthRepository):
    """模擬 TOCTOU 空窗：讀取時看到的是自助註冊列（kind 檢查因此放行），DB 實際已是管理者邀請。"""

    async def get_pending_by_email(self, db, email):  # type: ignore[override]
        row = await super().get_pending_by_email(db, email)
        if row is None:
            return None
        return SimpleNamespace(
            email=row.email,
            user_name=row.user_name,
            pwd_hash=None,
            kind=KIND_SELF_REGISTER,
            expires_date=row.expires_date,
        )


async def _seed_valid_invite(db) -> None:
    now = utcnow()
    await AuthRepository().create_pending_registration(
        db,
        token_hash=hash_token("invite-token"),
        email=_EMAIL,
        user_name="被邀請者",
        pwd_hash=None,
        expires_date=now + timedelta(hours=24),
        now=now,
        kind=KIND_ADMIN_INVITE,
        invite_id="INV00000001",
    )
    await db.commit()


async def test_resend_keeps_valid_admin_invite(db):
    """空窗內同 Email 已是仍有效的管理者邀請 → 該邀請不被刪除，重寄改回 409。"""
    await _seed_valid_invite(db)

    service = ResendVerificationService(repository=_WindowRepo())
    with pytest.raises(AppError) as err:
        await service.resend(db, email=_EMAIL)
    assert err.value.status_code == 409
    assert err.value.error_code == "DP_USER_005"

    # 撞 UNIQUE 後 session 需 rollback（production 由 get_db 負責）；已 commit 的邀請列應完好
    await db.rollback()
    row = (await db.execute(select(DpPendingRegistration).where(DpPendingRegistration.email == _EMAIL))).scalar_one()
    assert row.kind == KIND_ADMIN_INVITE
    assert row.invite_id == "INV00000001"
