"""認證端點（US1）：登入（匿名）。換發 / 登出 / module-summary 於後續 task 補。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.rate_limit import LOGIN_RATE_MAX, RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.dp.user.schemas import LoginRequest, LoginResponse
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
