"""忘記密碼服務（US3）：申請（產 token + 寄信）與重設（驗 token + 更新密碼）。

token 明文僅入信中連結、DB 存 SHA-256（research §5）；一次性（USED_DATE）+ 時效（EXPIRES_DATE），
同帳號重新申請作廢舊 token。防帳號列舉：申請一律成功語氣、帳號不存在不產 token / 不寄信。
重設更新密碼 + 追加歷程 + 作廢 token + 稽核；**不解除鎖定 / 停用**（FR-07）。
門檻值（RESET_TOKEN_TTL_MIN / MIN_LEN / CHAR_TYPES / HISTORY_COUNT）讀平台級 DP_PARAM（SRVDP001）。
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.password_policy import hash_password, is_reused, validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_TOKEN_TYPE = "PWD_RESET"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "PWD_RESET"
_FUNC_NAME = "DP-FORGOT"
_DEFAULT_TTL_MIN = 30
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_HISTORY_COUNT = 3
_TOKEN_INVALID_MSG = "連結已失效，請重新申請"  # noqa: S105 — 使用者訊息，非密碼


class ForgotPasswordService:
    """申請忘記密碼（US3 T028）：防列舉 + 一次性時效 token + SRVDP002 寄信。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()

    async def request(self, db: AsyncSession, *, email: str) -> None:
        """申請重設：帳號存在才作廢舊 token、產新 token 並寄信；不存在則靜默（防列舉）。

        token 建立與 outbox 寫入於呼叫方交易內（flush），由 get_db 於請求成功時一併 commit（原子）。
        """
        user = await self._repo.get_by_email(db, email)
        if user is None:
            return  # 防帳號列舉：不產 token、不寄信，端點一律回相同訊息

        now = utcnow()
        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        await self._repo.invalidate_active_reset_tokens(db, user_id=user.user_id, token_type=_TOKEN_TYPE, now=now)

        plaintext = generate_reset_token()
        await self._repo.create_reset_token(
            db,
            token_hash=hash_token(plaintext),
            user_id=user.user_id,
            token_type=_TOKEN_TYPE,
            expires_date=now + timedelta(minutes=ttl_min),
            operator_id=user.user_id,
            now=now,
        )
        reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[user.email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user.user_name, "reset_link": reset_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )


class ResetPasswordService:
    """以 token 重設密碼（US3 T029）：驗 token + 複雜度 + 重複性 + 更新 + 歷程 + 作廢 + 稽核。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def reset(self, db: AsyncSession, *, token: str, new_password: str, confirm_password: str) -> None:
        """重設密碼。

        Raises:
            AppError: 兩次不一致（422 DP_USER_002）、token 失效 / 已用 / 逾時（400 DP_PWD_005）、
                複雜度（422 DP_PWD_001/002）、重複性（422 DP_PWD_003）。
        """
        ip = get_client_ip()
        now = utcnow()
        if new_password != confirm_password:
            raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")

        token_hash = hash_token(token)
        row = await self._repo.get_reset_token_by_hash(db, token_hash, _TOKEN_TYPE)
        if row is None or row.used_date is not None or row.expires_date <= now:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        # 複雜度（一般使用者）+ 重複性（禁最近 HISTORY_COUNT 次）——於消費 token 前檢核，
        # 使複雜度 / 重複失敗時不白白作廢 token（使用者可用同連結重試）。
        min_len = await self._params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
        char_types = await self._params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
        validate_password_strength(new_password, min_length=min_len, required_char_types=char_types)
        history_count = await self._params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT)
        recent = await self._repo.recent_pwd_hashes(db, user.user_id, history_count)
        if is_reused(new_password, recent):
            raise AppError(status_code=422, detail="不可與最近使用過之密碼相同", error_code="DP_PWD_003")

        # 原子消費 token（關閉「查→標用」TOCTOU；並發同 token 只有一個成功）→ 作為後續寫入的閘
        if await self._repo.consume_reset_token(db, token_hash=token_hash, token_type=_TOKEN_TYPE, now=now) is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        # 更新（不改鎖定 / 停用）+ 追加歷程 + 稽核
        new_hash = hash_password(new_password)
        await self._repo.update_password(db, user=user, pwd_hash=new_hash, operator_id=user.user_id, now=now)
        seq_no = await self._repo.next_pwd_seq_no(db, user.user_id)
        await self._repo.add_pwd_history(
            db, user_id=user.user_id, seq_no=seq_no, pwd_hash=new_hash, operator_id=user.user_id, now=now
        )
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user.user_id,
            target_id=user.user_id,
            description="密碼重設",
            source_ip=ip,
        )
