"""忘記密碼服務（US3）：申請（產 token + 寄信）與重設（驗 token + 更新密碼）。

token 明文僅入信中連結、DB 存 SHA-256（research §5）；一次性（USED_DATE）+ 時效（EXPIRES_DATE），
同帳號重新申請作廢舊 token。防帳號列舉：申請一律成功語氣、帳號不存在不產 token / 不寄信。
重設更新密碼 + 追加歷程 + 作廢 token + 稽核；**不解除鎖定 / 停用**（FR-07）。
門檻值（RESET_TOKEN_TTL_MIN / MIN_LEN / ADMIN_MIN_LEN / CHAR_TYPES / HISTORY_COUNT）讀平台級 DP_PARAM（SRVDP001）。
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.password_hashing import hash_password_async, is_reused_async
from app.core.password_policy import validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.password_rules import PasswordRules, rules_for_user
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_TOKEN_TYPE = "PWD_RESET"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "PWD_RESET"
_FUNC_NAME = "DP-FORGOT"
_DEFAULT_TTL_MIN = 30
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

    async def password_rules_for_token(self, db: AsyncSession, *, token: str) -> PasswordRules:
        """重設頁適用之門檻（#623）：依 token 對應帳號判定；token 失效則拒絕（#673）。

        ⛔ **失效一律回同一個錯誤，不得依其帳號分歧**——否則端點會替已作廢的連結報出
        「這是管理者」。本方法對「查無 / 已用 / 逾期」三種失效回完全相同的 `DP_PWD_005`，
        與帳號是否為管理者無關；`test_重設規則端點_失效token的回應不因是否為管理者而異`
        以同一個字面量斷言四個組合來釘住它。

        ### #673 之前：失效回一般門檻、不報錯

        原設計讓失效 token 回一般門檻（8 字元）「維持重設頁原有的提示時點」，連結失效留到
        送出時由 `reset` 告知。但 `spec_us3` AC 3 要求「token 已逾時或已被使用，**點連結**時
        拒絕並提示（DP-MSG-DP09-002）」——推遲到送出與該 AC 衝突，且使用者會先照著
        **錯的門檻**（管理者看到 8、實際要 12）打完一組密碼才被擋下。

        Raises:
            AppError: token 查無 / 已用 / 逾期（400 DP_PWD_005），訊息與 `reset` 同一常數。

        Returns:
            與 `reset` 檢核所用相同之門檻（同一支 `rules_for_user`）。
        """
        row = await self._repo.get_reset_token_by_hash(db, hash_token(token), _TOKEN_TYPE)
        if row is None or row.used_date is not None or row.expires_date <= utcnow():
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        return await rules_for_user(db, row.user_id, params=self._params)

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

        # 複雜度 + 重複性（禁最近 HISTORY_COUNT 次）——於消費 token 前檢核，
        # 使複雜度 / 重複失敗時不白白作廢 token（使用者可用同連結重試）。
        # 長度門檻比照變更密碼依帳號判定（#623）：原本只讀 MIN_LEN，管理者可經忘記密碼繞過 12 字元。
        rules = await rules_for_user(db, user.user_id, params=self._params)
        validate_password_strength(new_password, min_length=rules.min_len, required_char_types=rules.char_types)
        history_count = await self._params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT)
        recent = await self._repo.recent_pwd_hashes(db, user.user_id, history_count)
        if await is_reused_async(new_password, recent):
            raise AppError(status_code=422, detail="不可與最近使用過之密碼相同", error_code="DP_PWD_003")

        # 先算雜湊再進寫入段：雜湊為純 CPU、不依賴 DB 結果，放在 consume_reset_token 之後會讓
        # 該 UPDATE 的交易多持有 ~185ms 的執行緒往返（#214 review 附帶發現）。
        new_hash = await hash_password_async(new_password)

        # 原子消費 token（關閉「查→標用」TOCTOU；並發同 token 只有一個成功）→ 作為後續寫入的閘
        if await self._repo.consume_reset_token(db, token_hash=token_hash, token_type=_TOKEN_TYPE, now=now) is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        # 更新（不改鎖定 / 停用）+ 追加歷程 + 稽核
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
