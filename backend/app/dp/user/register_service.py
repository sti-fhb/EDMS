"""註冊服務（US2 自助註冊，#56 方案 B：Email 驗證後啟用）。

伺服器端檢核（兩次一致 / Email 未被已驗證帳號佔用 / 密碼複雜度）→ **不建 DP_USER**，
改寫入待驗證表 `DP_PENDING_REGISTRATION`（Email / 姓名 / 密碼雜湊 + 一次性驗證 token）
並經發信服務（US6）寄「註冊驗證信」。點驗證連結通過後才由 verify_service 建 DP_USER。

一 Email 一筆待驗證：Email 已在 pending（未驗證）→ 覆蓋（刪舊列 + 新 token + 重寄）＝新註冊語意；
Email 已在 DP_USER（已驗證）→ 409（引導登入 / 忘記密碼）。明文 token 僅入信中連結、DB 存 SHA-256。
複雜度門檻讀平台級 DP_PARAM（一般使用者 MIN_LEN / CHAR_TYPES）；驗證 TTL 沿用既有 token 30 分。
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.password_policy import hash_password, validate_password_strength
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import NotifyService, ParamService

_EMAIL_TAKEN_MSG = "此 Email 已被註冊，請直接登入或使用忘記密碼"
_TEMPLATE_CODE = "ACCOUNT_VERIFY"
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_TTL_MIN = 30


class RegisterService:
    """SRVDP 自助註冊服務（US2）：檢核 → 寫待驗證表 + 寄驗證信（不建 DP_USER）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()

    async def register(
        self, db: AsyncSession, *, email: str, user_name: str, password: str, confirm_password: str
    ) -> None:
        """自助註冊：檢核 → 寫待驗證表 + 寄驗證信；**不建 DP_USER、不授角色、不記稽核**（移至驗證步）。

        提交由 get_db 於請求成功時負責；任一檢核失敗於寫入前拋 AppError，get_db rollback 無副作用。

        Raises:
            AppError: 兩次不一致（422 DP_USER_002）、Email 已被已驗證帳號佔用（409 DP_USER_001）、
                密碼不符複雜度（422 DP_PWD_001/002/004）。
        """
        # 1. 兩次一致（FR-02 伺服器端權威檢核，前端 Zod 另擋一次）
        if password != confirm_password:
            raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")
        # 2. Email 未被「已驗證帳號」佔用（未驗證的 pending 列於 step 4 覆蓋，不擋）
        if await self._repo.email_exists(db, email):
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_001")
        # 3. 密碼複雜度（一般使用者；validate_password_strength 拋 DP_PWD_001/002/004）
        min_len = await self._params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
        char_types = await self._params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
        validate_password_strength(password, min_length=min_len, required_char_types=char_types)

        # 4. 覆蓋同 Email 舊待驗證列（重新註冊 / 重寄語意）→ 寫新待驗證列（僅存 token SHA-256）
        now = utcnow()
        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        plaintext = generate_reset_token()
        await self._repo.delete_pending_by_email(db, email)
        try:
            await self._repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=email,
                user_name=user_name,
                pwd_hash=hash_password(password),
                expires_date=now + timedelta(minutes=ttl_min),
                now=now,
            )
        except IntegrityError as exc:
            # 同 Email 並發註冊 / 重寄競態：delete 後另一交易已搶插同 Email pending → 撞 UQ。
            # 轉乾淨 409（避免落通用 500）；使用者稍後重試或改走登入。
            raise AppError(
                status_code=409, detail="此 Email 註冊處理中，請稍後再試或直接登入", error_code="DP_USER_005"
            ) from exc
        # 5. 寄驗證信（US6；範本 MODULE=DP ACCOUNT_VERIFY）；連結以設定檔組（防 Host 注入）
        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )
