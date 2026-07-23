"""註冊驗證 / 重寄服務（US2 #56 方案 B）。

VerifyService：驗 token → 建 DP_USER（ACTIVE）+ 啟用副作用（首筆 PWD_HIST + 授 ET 學員 + 雙稽核）
+ 刪待驗證列。啟用副作用只在此驗證步落地（未驗證帳號不先佔角色 / 稽核）。冪等性以 DP_USER
EMAIL 唯一鍵為底層保證：重複 / 競態確認 → 第一個建成、其餘乾淨拒絕（409 DP_USER_001）。

ResendVerificationService：重寄驗證信（僅對 pending 帳號）；作廢舊 token（以 Email 覆蓋）、產新、重寄；
防列舉——無論該 Email 是否有待驗證列，端點一律回相同訊息。
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.activation import activate_pending_account
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_TEMPLATE_CODE = "ACCOUNT_VERIFY"
_FUNC_NAME = "DP-REGISTER"
_KIND_SELF_REGISTER = "SELF_REGISTER"
_DEFAULT_TTL_MIN = 30
_TOKEN_INVALID_MSG = "驗證連結無效"  # noqa: S105 — 使用者訊息，非密碼
_TOKEN_EXPIRED_MSG = "驗證連結已失效，請重新申請"  # noqa: S105 — 使用者訊息，非密碼


class VerifyService:
    """以驗證 token 啟用註冊：建 DP_USER + 啟用副作用 + 刪待驗證列。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._audit = audit or AuditLogService()

    async def verify(self, db: AsyncSession, *, token: str) -> None:
        """驗證註冊 token → 啟用帳號（啟用副作用重用 `activate_pending_account`，#67）。

        密碼來源＝pending.pwd_hash（註冊時所填）。

        Raises:
            AppError: token 無效（400 DP_USER_003）、逾時（400 DP_USER_004）、
                Email 已完成驗證 / 競態（409 DP_USER_001）。
        """
        now = utcnow()
        ip = get_client_ip()
        pending = await self._repo.get_pending_by_token_hash(db, hash_token(token))
        if pending is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_USER_003")
        if pending.expires_date <= now:
            raise AppError(status_code=400, detail=_TOKEN_EXPIRED_MSG, error_code="DP_USER_004")

        await activate_pending_account(
            db,
            pending=pending,
            pwd_hash=pending.pwd_hash,
            now=now,
            ip=ip,
            repo=self._repo,
            audit=self._audit,
            func_name=_FUNC_NAME,
            create_desc="使用者自助註冊（Email 驗證通過）",
        )


class ResendVerificationService:
    """重寄註冊驗證信（僅對 pending 帳號）；防列舉：一律回相同訊息。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()

    async def resend(self, db: AsyncSession, *, email: str) -> None:
        """重寄：pending 存在才作廢舊 token、產新並重寄；不存在則靜默（防列舉）。

        僅處理自助註冊（SELF_REGISTER）；管理者邀請（ADMIN_INVITE）之重寄走使用者管理頁（US4 #67），
        不經此匿名端點，故遇邀請列一律靜默（等同不存在，維持防列舉）。
        """
        pending = await self._repo.get_pending_by_email(db, email)
        if pending is None or pending.kind != _KIND_SELF_REGISTER:
            return

        now = utcnow()
        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        plaintext = generate_reset_token()
        # 以 Email 覆蓋：刪舊列（舊 token 即作廢）→ 沿用原姓名 / 密碼雜湊寫新列
        await self._repo.delete_pending_by_email(db, email)
        try:
            await self._repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=pending.email,
                user_name=pending.user_name,
                pwd_hash=pending.pwd_hash,
                expires_date=now + timedelta(minutes=ttl_min),
                now=now,
            )
        except IntegrityError as exc:
            # 並發重寄 / 註冊競態：另一交易已搶插同 Email pending → 撞 UQ。轉乾淨 409（交 get_db
            # rollback，避免對失敗 session commit）。僅發生於「pending 已存在」下的競態，不洩露存在性。
            raise AppError(
                status_code=409, detail="此 Email 註冊處理中，請稍後再試或直接登入", error_code="DP_USER_005"
            ) from exc
        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": pending.user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )
