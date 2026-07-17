"""認證服務（US1）：登入 / 換發 / 登出。

帳密驗證（bcrypt）、錯誤分流（帳號不存在 / 密碼錯誤，明確訊息 spec_us1 Clarification）、
失敗計數與自動鎖定、成功核發 JWT（auth_time + 短 TTL）；登入 / 登出 / 鎖定寫稽核（SRVDP003，含來源 IP）。
門檻值（FAIL_LOCK_COUNT / LOCK_MINUTES / ACCESS_TTL_MIN / EXPIRY_DAYS）讀平台級 DP_PARAM（SRVDP001）。
"""

from datetime import timedelta
from typing import NoReturn

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, create_access_token
from app.core.exceptions import AppError
from app.core.password_policy import is_password_expired, verify_password
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.schemas import LoginResponse, TokenResponse
from app.services import AuditLogService, ParamService

_SYSTEM_USER = "SYSTEM"
# DP_PARAM 讀取失敗的保底值（對齊 T009 種子）
_DEFAULT_FAIL_LOCK_COUNT = 5
_DEFAULT_LOCK_MINUTES = 30
_DEFAULT_ACCESS_TTL_MIN = 15
_DEFAULT_EXPIRY_DAYS = 90
_DEFAULT_RENEW_MAX_HOURS = 8


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
            await self._fail(db, _SYSTEM_USER, ip, "帳號不存在", 401, "查無此帳號，請先註冊", "DP_AUTH_007")

        if user.locked_until is not None and user.locked_until > now:
            await self._fail(db, user.user_id, ip, "帳號鎖定中", 403, "帳號已鎖定，請洽管理者或稍後再試", "DP_AUTH_005")
        if user.status != "ACTIVE":
            await self._fail(db, user.user_id, ip, "帳號已停用", 403, "帳號已停用，請洽管理者", "DP_AUTH_004")

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
            await self._fail(db, user.user_id, ip, reason, 401, "密碼錯誤", "DP_AUTH_008")

        # 成功：重設計數 / 清鎖 / 更新 last_login、核發 JWT（提交由 get_db 於請求成功時負責）
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
        await self._audit_auth(db, user.user_id, "LOGIN", "SUCCESS", ip, None)
        return LoginResponse(access_token=token, must_change_pwd=must_change)

    async def renew(self, db: AsyncSession, *, payload: JwtPayload) -> TokenResponse:
        """活動換發：沿用原 auth_time 重簽、套用單日換發上限。

        DP_USER 狀態閘（停用 / 鎖定 / 已刪）由端點層 get_jwt_payload 於本方法前完成（#16 Security L-1）；
        此處僅檢核距 auth_time 是否逾單日換發上限。無 DB 寫入，逾限拋錯不需落地。

        Raises:
            AppError: 距 auth_time 已逾換發上限（401 DP_AUTH_003）。
        """
        renew_max = await self._int_param(db, "JWT", "RENEW_MAX_HOURS", _DEFAULT_RENEW_MAX_HOURS)
        if utcnow() - payload.auth_time >= timedelta(hours=renew_max):
            raise AppError(status_code=401, detail="已達單次登入時數上限，請重新登入", error_code="DP_AUTH_003")
        ttl = await self._int_param(db, "JWT", "ACCESS_TTL_MIN", _DEFAULT_ACCESS_TTL_MIN)
        token = create_access_token(sub=payload.sub, ttl_minutes=ttl, auth_time=payload.auth_time)
        return TokenResponse(access_token=token)

    async def logout(self, db: AsyncSession, *, user_id: str) -> None:
        """登出：寫 LOGOUT 稽核（無狀態 JWT，不做伺服端撤銷）。提交由 get_db 於請求成功時負責。"""
        await self._audit_auth(db, user_id, "LOGOUT", "SUCCESS", get_client_ip(), None)

    async def _fail(
        self,
        db: AsyncSession,
        operator_id: str,
        ip: str | None,
        reason: str,
        status_code: int,
        detail: str,
        error_code: str,
    ) -> NoReturn:
        """寫 LOGIN FAIL 稽核並**提交**後拋 AppError。

        登入失敗的副作用（鎖定計數 / 鎖定時間 / FAIL 稽核）必須在本請求以錯誤回應時仍落地——
        否則 get_db 對 AppError 的 rollback 會一併抹除，造成帳號鎖定機制失效、失敗稽核漏記。
        故此處顯式 commit；測試以 savepoint 隔離（見 conftest db fixture），commit 僅釋放 savepoint
        不破壞隔離。
        """
        await self._audit_auth(db, operator_id, "LOGIN", "FAIL", ip, reason)
        await db.commit()
        raise AppError(status_code=status_code, detail=detail, error_code=error_code)

    async def _int_param(self, db: AsyncSession, param_id: str, key: str, default: int) -> int:
        raw = await self._params.get_param_value(db, param_id, key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def _audit_auth(
        self,
        db: AsyncSession,
        operator_id: str,
        action_type: str,
        result: str,
        ip: str | None,
        desc: str | None,
    ) -> None:
        await self._audit.log_action(
            db,
            module="DP",
            func_name="DP-AUTH",
            action_type=action_type,
            result=result,
            operator_id=operator_id,
            description=desc,
            source_ip=ip,
        )
