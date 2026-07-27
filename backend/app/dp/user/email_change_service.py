"""帳號（Email）變更服務（US8）：申請（唯一檢核 + 產 token + 寄新信箱）與驗證（切換 EMAIL）。

延遲生效（FR-03）：申請時不動 DP_USER.EMAIL，僅產一次性 EMAIL_CHANGE token（帶 NEW_EMAIL）並寫
PENDING_EMAIL、寄驗證信至**新信箱**；驗證前舊 Email 仍可登入。點連結驗證通過才切 EMAIL、清 PENDING、
作廢 token、寫稽核（含前後值）；逾時 / 已用一律作廢。token 明文入信、DB 存 SHA-256（research §5）。

重用 DP_PWD_RESET（TOKEN_TYPE=EMAIL_CHANGE）與忘記密碼共構（token.py / repository token 方法）。
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_TOKEN_TYPE = "EMAIL_CHANGE"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "EMAIL_CHANGE_VERIFY"  # 信件範本代碼
_FUNC_NAME = "DP-PROFILE"
_DEFAULT_TTL_MIN = 30
_TOKEN_INVALID_MSG = "連結已失效，Email 變更作廢，原 Email 維持有效"  # noqa: S105 — 使用者訊息，非密碼


class EmailChangeService:
    """Email 變更（US8 T038）：申請寄新信箱驗證信 + 點連結後切換。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()
        self._audit = audit or AuditLogService()

    async def request(self, db: AsyncSession, *, user_id: str, new_email: str) -> None:
        """申請 Email 變更：新信箱唯一檢核 → 作廢舊 token → 產新 token + PENDING_EMAIL → 寄新信箱。

        Raises:
            AppError: 查無帳號（404 DP_USER_008）、新 Email 已被使用（409 DP_USER_007）。
        """
        now = utcnow()
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail="查無此帳號", error_code="DP_USER_008")
        # 新信箱唯一：已被任一帳號使用或他人待驗證中即擋（延遲切換窗口，含軟刪除；亦擋「改為自己現用信箱」）
        if await self._repo.email_taken_for_change(db, new_email, requester_id=user_id):
            raise AppError(status_code=409, detail="此 Email 已被使用", error_code="DP_USER_007")

        ttl_min = await self._params.get_int_param(db, "LOGIN", "EMAIL_CHANGE_TTL_MIN", _DEFAULT_TTL_MIN)
        await self._repo.invalidate_active_reset_tokens(db, user_id=user_id, token_type=_TOKEN_TYPE, now=now)

        plaintext = generate_reset_token()
        await self._repo.create_reset_token(
            db,
            token_hash=hash_token(plaintext),
            user_id=user_id,
            token_type=_TOKEN_TYPE,
            expires_date=now + timedelta(minutes=ttl_min),
            operator_id=user_id,
            now=now,
            new_email=new_email,
        )
        await self._repo.set_pending_email(db, user=user, pending_email=new_email, operator_id=user_id, now=now)

        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email-change?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[new_email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user.user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )

    async def verify(self, db: AsyncSession, *, token: str) -> None:
        """以 token 完成 Email 變更：原子消費 token → 切 EMAIL + 清 PENDING + 稽核（前後值）。

        Raises:
            AppError: token 失效 / 已用 / 逾時（400 DP_PWD_005）、查無帳號（400 DP_PWD_005）。
        """
        now = utcnow()
        consumed = await self._repo.consume_email_change_token(db, token_hash=hash_token(token), now=now)
        if consumed is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        user_id, new_email = consumed
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        before_email = user.email
        # 縱深防禦：request 時的唯一性檢核與此處消費間仍有 TTL 窗口，若期間他人搶用同一 Email，
        # DB 之 UQ_DP_USER_EMAIL 會於 flush 拋 IntegrityError；攔下轉乾淨 409（避免落成未處理 500）。
        try:
            await self._repo.switch_email(db, user=user, new_email=new_email, operator_id=user_id, now=now)
        except IntegrityError as exc:
            raise AppError(status_code=409, detail="此 Email 已被使用", error_code="DP_USER_007") from exc
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user_id,
            target_id=user_id,
            description="Email 變更",
            before_value={"email": before_email},
            after_value={"email": new_email},
            source_ip=get_client_ip(),
        )
