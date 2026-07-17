"""認證服務（US1）：登入 / 換發 / 登出。

帳密驗證（bcrypt）、錯誤分流（帳號不存在 / 密碼錯誤，明確訊息 spec_us1 Clarification）、
失敗計數與自動鎖定、成功核發 JWT（auth_time + 短 TTL）；登入 / 登出 / 鎖定寫稽核（SRVDP003，含來源 IP）。
門檻值（FAIL_LOCK_COUNT / LOCK_MINUTES / ACCESS_TTL_MIN / EXPIRY_DAYS）讀平台級 DP_PARAM（SRVDP001）。
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.password_policy import is_password_expired, verify_password
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.schemas import LoginResponse
from app.services import AuditLogService, ParamService

_SYSTEM_USER = "SYSTEM"
# DP_PARAM 讀取失敗的保底值（對齊 T009 種子）
_DEFAULT_FAIL_LOCK_COUNT = 5
_DEFAULT_LOCK_MINUTES = 30
_DEFAULT_ACCESS_TTL_MIN = 15
_DEFAULT_EXPIRY_DAYS = 90


class AuthService:
    """SRVDP 認證服務（登入 / 換發 / 登出）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def login(self, db: AsyncSession, *, email: str, password: str) -> LoginResponse:
        """帳密登入：驗證 → 核發 JWT，並寫登入稽核。

        Raises:
            AppError: 帳號不存在（401 DP_AUTH_007）、密碼錯誤（401 DP_AUTH_008）、
                鎖定中（403 DP_AUTH_005）、停用（403 DP_AUTH_004）。
        """
        ip = get_client_ip()
        now = utcnow()
        user = await self._repo.get_by_email(db, email)
        if user is None:
            await self._audit_login(db, _SYSTEM_USER, "FAIL", ip, "帳號不存在")
            raise AppError(status_code=401, detail="查無此帳號，請先註冊", error_code="DP_AUTH_007")

        if user.locked_until is not None and user.locked_until > now:
            await self._audit_login(db, user.user_id, "FAIL", ip, "帳號鎖定中")
            raise AppError(status_code=403, detail="帳號已鎖定，請洽管理者或稍後再試", error_code="DP_AUTH_005")
        if user.status != "ACTIVE":
            await self._audit_login(db, user.user_id, "FAIL", ip, "帳號已停用")
            raise AppError(status_code=403, detail="帳號已停用，請洽管理者", error_code="DP_AUTH_004")

        if not verify_password(password, user.pwd_hash):
            user.login_fail_count += 1
            fail_lock = await self._int_param(db, "LOGIN", "FAIL_LOCK_COUNT", _DEFAULT_FAIL_LOCK_COUNT)
            reason = "密碼錯誤"
            if user.login_fail_count >= fail_lock:
                lock_min = await self._int_param(db, "LOGIN", "LOCK_MINUTES", _DEFAULT_LOCK_MINUTES)
                user.locked_until = now + timedelta(minutes=lock_min)
                reason = "連續失敗達上限，帳號鎖定"
            user.updated_user = _SYSTEM_USER
            user.updated_date = now
            await db.flush()
            await self._audit_login(db, user.user_id, "FAIL", ip, reason)
            raise AppError(status_code=401, detail="密碼錯誤", error_code="DP_AUTH_008")

        # 成功：重設計數 / 清鎖 / 更新 last_login、核發 JWT
        user.login_fail_count = 0
        user.locked_until = None
        user.last_login_date = now
        user.updated_user = _SYSTEM_USER
        user.updated_date = now
        ttl = await self._int_param(db, "JWT", "ACCESS_TTL_MIN", _DEFAULT_ACCESS_TTL_MIN)
        token = create_access_token(sub=user.user_id, ttl_minutes=ttl)
        expiry_days = await self._int_param(db, "PWD_POLICY", "EXPIRY_DAYS", _DEFAULT_EXPIRY_DAYS)
        must_change = user.must_change_pwd or is_password_expired(user.pwd_changed_date, expiry_days, now=now)
        await db.flush()
        await self._audit_login(db, user.user_id, "SUCCESS", ip, None)
        return LoginResponse(access_token=token, must_change_pwd=must_change)

    async def _int_param(self, db: AsyncSession, param_id: str, key: str, default: int) -> int:
        raw = await self._params.get_param_value(db, param_id, key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def _audit_login(
        self, db: AsyncSession, operator_id: str, result: str, ip: str | None, desc: str | None
    ) -> None:
        await self._audit.log_action(
            db,
            module="DP",
            func_name="DP-AUTH",
            action_type="LOGIN",
            result=result,
            operator_id=operator_id,
            description=desc,
            source_ip=ip,
        )
