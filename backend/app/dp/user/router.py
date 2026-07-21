"""認證端點（US1 / US2 / US3）：登入 / 註冊 / 忘記密碼 / 重設密碼（匿名）/ 換發 / 登出 / 入口頁模組摘要。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.module_roles import module_role_gate
from app.core.password_gate import require_password_current
from app.core.rate_limit import LOGIN_RATE_MAX, RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.register_service import RegisterService
from app.dp.user.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ModuleRoleStatus,
    ModuleSummary,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.dp.user.service import AuthService

# 登入限流器（行程內；IP 與帳號維度共用同一器、以 key 前綴區分）
_login_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊限流器（IP 維度；防批量灌帳號）
_register_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 忘記密碼申請 / 重設限流器（IP + 帳號維度；防列舉與暴力）
_forgot_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_reset_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

router = APIRouter(prefix="/api", tags=["auth"])
_service = AuthService()
_register_service = RegisterService()
_forgot_service = ForgotPasswordService()
_reset_service = ResetPasswordService()

_FORGOT_MESSAGE = "若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_login_limiter, "login")),
) -> LoginResponse:
    """帳密登入（匿名端點）。IP + 帳號雙維度限流；帳號維度**先 hit 限流、後查存在性**防列舉。"""
    _login_limiter.hit(f"login:acct:{data.email}")
    return await _service.login(db, email=data.email, password=data.password)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_register_limiter, "register")),
) -> None:
    """自助註冊（匿名端點，IP 限流防批量灌帳號）。伺服器端檢核 → 建帳號 + 授 ET 學員 + 雙稽核，回 201。"""
    await _register_service.register(
        db,
        email=data.email,
        user_name=data.user_name,
        password=data.password,
        confirm_password=data.confirm_password,
    )


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
