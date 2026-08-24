"""認證端點（US1 / US2 / US3）：登入 / 註冊 / 忘記密碼 / 重設密碼（匿名）/ 換發 / 登出 / 入口頁模組摘要。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.cooldown import VerifySendCooldown
from app.core.db import get_db
from app.core.module_roles import module_role_gate
from app.core.operator import OperatorInfo, get_operator
from app.core.password_gate import require_password_current
from app.core.rate_limit import (
    LOGIN_RATE_MAX,
    RATE_WINDOW_SECONDS,
    REGISTER_RATE_MAX,
    SlidingWindowRateLimiter,
    rate_limit_by_ip,
)
from app.dp.user.activate_service import ActivateAccountService
from app.dp.user.email_change_service import EmailChangeService
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.profile_service import ProfileService
from app.dp.user.register_service import RegisterService
from app.dp.user.schemas import (
    ActivateAccountRequest,
    EmailChangeRequest,
    EmailChangeVerify,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ModuleRoleStatus,
    ModuleSummary,
    NameUpdate,
    PasswordChange,
    PasswordPolicyResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.dp.user.service import AuthService
from app.dp.user.verify_service import ResendVerificationService, VerifyService
from app.services import ParamService

# 登入限流器（行程內；IP 與帳號維度共用同一器、以 key 前綴區分）
_login_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊限流器（IP 維度；防批量灌帳號）
# 註冊為匿名寫入型端點，門檻較登入嚴（#44）；IP 與帳號兩維度共用此實例
_register_limiter = SlidingWindowRateLimiter(max_requests=REGISTER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 忘記密碼申請 / 重設限流器（IP + 帳號維度；防列舉與暴力）
_forgot_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_reset_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊驗證端點限流器（IP 維度）；重寄另加帳號維度防濫發
_verify_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_resend_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 帳號啟用端點限流器（IP 維度；受邀者持 token 設密碼）
_activate_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 密碼變更 / Email 變更申請限流器（IP + 帳號維度；US8 FR-07 防高頻嘗試）
_pwd_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_email_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# Email 變更驗證端點限流器（IP 維度；公開落點）
_verify_email_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# Email 變更寄信冷卻（比照註冊 #74）：同帳號兩次寄驗證信間隔至少 VERIFY_SEND_COOLDOWN_SEC（預設 10 分）
_email_change_cooldown = VerifySendCooldown()
# 驗證信寄送冷卻（#74）：register 與 resend 共用同一器、同一 Email key，
# 600 秒內對同一 Email 只放行一封（堵「以重新註冊繞過重寄冷卻」）
_verify_send_cooldown = VerifySendCooldown()
_params = ParamService()
_VERIFY_SEND_COOLDOWN_DEFAULT = 600


def _verify_send_key(email: str) -> str:
    """驗證信寄送冷卻分桶鍵（register / resend 共用同一 Email 額度）。"""
    return f"verify-send:acct:{email}"


router = APIRouter(prefix="/api", tags=["auth"])
_service = AuthService()
_register_service = RegisterService()
_verify_service = VerifyService()
_resend_service = ResendVerificationService()
_forgot_service = ForgotPasswordService()
_reset_service = ResetPasswordService()
_activate_service = ActivateAccountService()
_profile_service = ProfileService()
_email_change_service = EmailChangeService()

_DEFAULT_MIN_LEN = 8
_DEFAULT_ADMIN_MIN_LEN = 12
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_HISTORY_COUNT = 3
_DEFAULT_EXPIRY_DAYS = 90

_FORGOT_MESSAGE = "若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"
_REGISTER_MESSAGE = "驗證信已寄至您的信箱，請於 30 分鐘內點連結完成驗證"
_RESEND_MESSAGE = "若該 Email 有待驗證的註冊，驗證信將重新寄出，請於 30 分鐘內完成驗證"


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_login_limiter, "login")),
) -> LoginResponse:
    """帳密登入（匿名端點）。IP + 帳號雙維度限流；帳號維度**先 hit 限流、後查存在性**防列舉。"""
    _login_limiter.hit(f"login:acct:{data.email}")
    return await _service.login(db, email=data.email, password=data.password)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_register_limiter, "register")),
) -> dict[str, object]:
    """自助註冊（匿名端點，IP 限流防批量灌帳號）。

    方案 B（#56）：檢核 → 寫待驗證表 + 寄驗證信（**不建 DP_USER**），回 202（已受理、待驗證）。
    使用者點信中連結經 /verify-email 通過後才建帳號並啟用。

    帳號維度限流（先 hit、後查）：防輪換 IP 對單一 Email 反覆觸發驗證信（email-bombing），
    與 forgot / resend 一致。

    驗證信寄送冷卻（#74）：check 於檢核前（防列舉）、record 於送信成功後——註冊檢核失敗
    （422/409）不 record，不誤觸冷卻；與 resend 共用同一 Email 額度，堵住繞道重發。

    例外（#86）：**已驗證帳號**的存在性檢核置於冷卻之前。防列舉在此無實益——register 本來
    就以 409「已被註冊」對外洩露已驗證 Email 的存在（冷卻窗外即可分辨），冷卻期擋著只是讓
    使用者白等倒數。pending / 全新 Email 維持冷卻優先，防狂發語意不變。
    """
    _register_limiter.hit(f"register:acct:{data.email}")
    # 已驗證帳號優先於冷卻回應（#86）：該狀態是終局的，等倒數結束也不會變，
    # 且此路徑本來就不送信、冷卻無防狂發價值——先擋可免使用者白等一輪。
    await _register_service.assert_email_not_registered(db, data.email)
    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    key = _verify_send_key(data.email)
    _verify_send_cooldown.check(key, cooldown_sec)
    await _register_service.register(
        db,
        email=data.email,
        user_name=data.user_name,
        password=data.password,
        confirm_password=data.confirm_password,
    )
    _verify_send_cooldown.record(key)
    return {"message": _REGISTER_MESSAGE, "retry_after": cooldown_sec}


@router.post("/verify-email")
async def verify_email(
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_verify_limiter, "verify")),
) -> dict[str, str]:
    """驗證註冊 token（匿名，持信中連結 token）→ 建 DP_USER + 授 ET 學員 + 雙稽核 + 刪待驗證列。"""
    await _verify_service.verify(db, token=data.token)
    return {"message": "帳號已啟用，請以新帳號登入"}


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_resend_limiter, "resend")),
) -> dict[str, object]:
    """重寄註冊驗證信（匿名）。一律回相同訊息（防列舉）；僅對待驗證帳號作廢舊 token、產新並重寄。

    帳號維度**先 hit 限流、後查存在性**（同 forgot，防以 429 反推）。

    驗證信寄送冷卻（#74）：check 於查存在性前、record 於服務返回後——對存在 / 不存在的
    Email 皆 record，故 429 不因帳號是否存在而異（防列舉）；與 register 共用同一 Email 額度。
    成功回應帶 retry_after（＝完整冷卻秒數）供前端起算倒數。
    """
    _resend_limiter.hit(f"resend:acct:{data.email}")
    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    key = _verify_send_key(data.email)
    _verify_send_cooldown.check(key, cooldown_sec)
    await _resend_service.resend(db, email=data.email)
    _verify_send_cooldown.record(key)
    return {"message": _RESEND_MESSAGE, "retry_after": cooldown_sec}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_forgot_limiter, "forgot")),
) -> dict[str, str]:
    """忘記密碼申請（匿名）。一律回相同訊息（防列舉）；帳號存在才產 token 並寄信。

    帳號維度**先 hit 限流、後查存在性**（同登入，防以 429 反推帳號）。
    """
    _forgot_limiter.hit(f"forgot:acct:{data.email}")
    await _forgot_service.request(db, email=data.email)
    return {"message": _FORGOT_MESSAGE}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_reset_limiter, "reset")),
) -> dict[str, str]:
    """以 token 重設密碼（匿名，持信中連結 token）。驗 token + 複雜度 + 重複性 → 更新 + 作廢 + 稽核。"""
    await _reset_service.reset(
        db, token=data.token, new_password=data.new_password, confirm_password=data.confirm_password
    )
    return {"message": "密碼已更新，請以新密碼登入"}


@router.post("/activate-account")
async def activate_account(
    data: ActivateAccountRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_activate_limiter, "activate")),
) -> dict[str, str]:
    """帳號啟用（匿名，持邀請信連結 token，US4 #67）。

    受邀者自設密碼 → 驗 token（僅 ADMIN_INVITE）+ 效期 + 複雜度 → 建 DP_USER(ACTIVE) + 授 ET 學員
    + 雙稽核 + 首筆 PWD_HIST + 刪待邀請列（重用 activate_pending_account）。
    """
    await _activate_service.activate(
        db, token=data.token, new_password=data.new_password, confirm_password=data.confirm_password
    )
    return {"message": "帳號已啟用，請以新密碼登入"}


@router.post("/dp/user/renew", response_model=TokenResponse)
async def renew(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """活動換發：需現行有效 token。get_jwt_payload 先過 DP_USER 狀態閘，再驗單日換發上限重簽。"""
    return await _service.renew(db, payload=payload)


@router.post("/dp/user/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> None:
    """登出：需認證。寫 LOGOUT 稽核後回 204（無狀態 JWT，前端自行丟棄 token）。"""
    await _service.logout(db, user_id=payload.sub)


@router.get("/dp/user/module-summary", response_model=ModuleSummary)
async def module_summary(
    payload: JwtPayload = Depends(require_password_current),
    db: AsyncSession = Depends(get_db),
) -> ModuleSummary:
    """入口頁 / 側欄模組摘要：需認證且密碼現行有效（強制變更者擋於閘）。

    ET / DM 皆經 `has_any_role` 判定閘聚合（contracts §4）；未註冊模組 fail-closed
    回 False＝未開通。

    > **ET 原為寫死 `True`**（理由：學員為預設角色、人人皆有），因當時 ET 尚未註冊
    > checker、問閘必得 False，側欄會永遠不顯示「教育訓練」。#185 接線後該權宜前提
    > 消失，且變成錯誤來源——管理者於 DP 後台**取消**某人之學員角色後（#185 開通此
    > 能力），側欄仍會顯示 ET 群組，但其所有 ET 端點都會被存取閘以 403
    > `ET_AUTH_001` 擋下。改為實查使 側欄與存取閘一致。
    """
    et_has_role = await module_role_gate.has_any_role("ET", payload.sub, db)
    dm_has_role = await module_role_gate.has_any_role("DM", payload.sub, db)
    return ModuleSummary(
        et=ModuleRoleStatus(has_role=et_has_role),
        dm=ModuleRoleStatus(has_role=dm_has_role),
    )


# --- 個人資料維護（US8 /me；需認證，不套 require_password_current 逃生門） ---


@router.get("/dp/user/me", response_model=MeResponse)
async def get_me(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """本人個人資料：姓名 / 帳號（Email）/ 待驗證新信箱。"""
    user = await _profile_service.get_me(db, user_id=payload.sub)
    return MeResponse.model_validate(user)


@router.put("/dp/user/me", status_code=status.HTTP_204_NO_CONTENT)
async def update_me(
    data: NameUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> None:
    """變更姓名（直接生效、ET / DM 同步）+ 稽核。"""
    await _profile_service.update_name(db, user_id=operator.user_id, user_name=data.user_name)


@router.put("/dp/user/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
    _ip_limit: None = Depends(rate_limit_by_ip(_pwd_change_limiter, "pwd-change")),
) -> None:
    """變更密碼（含強制變更收尾）：驗舊 + 兩次一致 + 複雜度（特權 12）+ 重複性。

    IP + 帳號雙維度限流（FR-07）；帳號維度先 hit 後執行。
    """
    _pwd_change_limiter.hit(f"pwd-change:acct:{operator.user_id}")
    await _profile_service.change_password(
        db,
        user_id=operator.user_id,
        old_password=data.old_password,
        new_password=data.new_password,
        confirm_password=data.confirm_password,
    )


@router.put("/dp/user/me/email", status_code=status.HTTP_202_ACCEPTED)
async def change_email(
    data: EmailChangeRequest,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
    _ip_limit: None = Depends(rate_limit_by_ip(_email_change_limiter, "email-change")),
) -> dict[str, object]:
    """申請 Email 變更（延遲生效）：唯一檢核 → 產 token + PENDING_EMAIL → 寄驗證信至新信箱。

    寄信冷卻（#74，預設 10 分）：check 於送信前擋、record 於送信成功後蓋章——唯一性失敗（409）
    不誤觸冷卻。成功回應帶 retry_after（＝冷卻秒數）供前端起算倒數。
    """
    _email_change_limiter.hit(f"email-change:acct:{operator.user_id}")
    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    key = f"email-change-send:acct:{operator.user_id}"
    _email_change_cooldown.check(key, cooldown_sec)
    await _email_change_service.request(db, user_id=operator.user_id, new_email=data.new_email)
    _email_change_cooldown.record(key)
    return {
        "message": "驗證信已寄至新 Email，請於效期內完成驗證；驗證前原 Email 仍可登入",
        "retry_after": cooldown_sec,
    }


@router.post("/verify-email-change")
async def verify_email_change(
    data: EmailChangeVerify,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_verify_email_change_limiter, "verify-email-change")),
) -> dict[str, str]:
    """完成 Email 變更（公開，持信中連結 token）：消 token → 切 EMAIL + 稽核。"""
    await _email_change_service.verify(db, token=data.token)
    return {"message": "Email 已變更，請以新 Email 登入"}


@router.get("/password-policy", response_model=PasswordPolicyResponse)
async def get_password_policy(db: AsyncSession = Depends(get_db)) -> PasswordPolicyResponse:
    """公開密碼政策（併 #77 核心）：供變更密碼 / 註冊 / 重設頁動態渲染提示；僅非機密數值、即時不快取。"""
    return PasswordPolicyResponse(
        min_len=await _params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN),
        admin_min_len=await _params.get_int_param(db, "PWD_POLICY", "ADMIN_MIN_LEN", _DEFAULT_ADMIN_MIN_LEN),
        char_types=await _params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES),
        history_count=await _params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT),
        expiry_days=await _params.get_int_param(db, "PWD_POLICY", "EXPIRY_DAYS", _DEFAULT_EXPIRY_DAYS),
    )
