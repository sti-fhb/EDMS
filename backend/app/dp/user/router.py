"""認證端點（US1 / US2 / US3）：登入 / 註冊 / 忘記密碼 / 重設密碼（匿名）/ 換發 / 登出 / 入口頁模組摘要。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.cooldown import VerifySendCooldown
from app.core.db import get_db
from app.core.module_roles import module_role_gate
from app.core.password_gate import require_password_current
from app.core.rate_limit import LOGIN_RATE_MAX, RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.dp.user.activate_service import ActivateAccountService
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.register_service import RegisterService
from app.dp.user.schemas import (
    ActivateAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ModuleRoleStatus,
    ModuleSummary,
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
_register_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 忘記密碼申請 / 重設限流器（IP + 帳號維度；防列舉與暴力）
_forgot_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_reset_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊驗證端點限流器（IP 維度）；重寄另加帳號維度防濫發
_verify_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_resend_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 帳號啟用端點限流器（IP 維度；受邀者持 token 設密碼）
_activate_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
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
    """
    _register_limiter.hit(f"register:acct:{data.email}")
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
    """入口頁模組摘要：需認證且密碼現行有效（強制變更者擋於閘）。

    ET 恆可用（學員預設，contracts §4）；DM 具任一角色才可進入，經 has_any_role 判定閘聚合
    （ET / DM 模組未接線前 fail-closed 回 False＝未開通，待 US7 + 模組 service 落地）。
    """
    dm_has_role = await module_role_gate.has_any_role("DM", payload.sub, db)
    return ModuleSummary(
        et=ModuleRoleStatus(has_role=True),
        dm=ModuleRoleStatus(has_role=dm_has_role),
    )
