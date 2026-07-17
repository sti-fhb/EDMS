"""認證端點（US1）：登入（匿名）/ 換發 / 登出。module-summary 於 T025 補。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.rate_limit import LOGIN_RATE_MAX, RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.dp.user.schemas import LoginRequest, LoginResponse, TokenResponse
from app.dp.user.service import AuthService

# 登入限流器（行程內；IP 與帳號維度共用同一器、以 key 前綴區分）
_login_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

router = APIRouter(prefix="/api", tags=["auth"])
_service = AuthService()


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_login_limiter, "login")),
) -> LoginResponse:
    """帳密登入（匿名端點）。IP + 帳號雙維度限流；帳號維度**先 hit 限流、後查存在性**防列舉。"""
    _login_limiter.hit(f"login:acct:{data.email}")
    return await _service.login(db, email=data.email, password=data.password)


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
