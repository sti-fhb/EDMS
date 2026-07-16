import asyncio
import logging
import tomllib
import traceback
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip, set_client_ip
from app.dp.notify.mailer import SmtpMailer
from app.dp.notify.worker import run_forever

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    """啟停常駐發信 worker（SRVDP002 outbox 消費者，非排程 job）。"""
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_forever(SmtpMailer(), stop_event))
    try:
        yield
    finally:
        # 先請 worker 優雅收斂（跑完當前 cycle 並 commit），逾時才強制取消——
        # 避免在「已透過 SMTP 寄出、尚未 commit」的空窗被 cancel 導致 rollback 後重送。
        stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=30)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


class VersionResponse(BaseModel):
    version: str


class ClientInfoResponse(BaseModel):
    ip: str | None
    is_ipv6: bool


# 啟動時讀取一次版本號，避免每次請求都讀檔
def _read_version() -> str:
    pyproject_path = Path(__file__).parent / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as e:
        logger.warning("無法讀取 pyproject.toml 版本號：%s，使用預設值 unknown", e)
        return "unknown"


_APP_VERSION = _read_version()


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def client_ip_middleware(request: Request, call_next):
    """每個 request 進入時自動記錄 client IP 至 contextvars。

    優先從 X-Forwarded-For header 取得真實 IP（反向代理場景），
    fallback 到 request.client.host。
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None
    set_client_ip(client_ip)
    try:
        return await call_next(request)
    finally:
        set_client_ip(None)


# 各業務模組的 router 於後續 task 開發時在此 include。


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """將 AppError 統一轉換為標準錯誤回應格式。

    回傳格式：{"error_code": "...", "error_message": "..."}
    debug log 保留完整錯誤細節供後端排查，不對外暴露。
    """
    logger.debug("AppError %s %s: [%s] %s", request.method, request.url.path, exc.error_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "error_message": exc.detail},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """將框架層 HTTPException（如 404 路由不存在、405 Method Not Allowed）轉換為標準格式。

    error_code 格式為 HTTP_{status_code}，例如 HTTP_404、HTTP_405。
    AppError 因有更精確的 handler，不會走到此處。
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": f"HTTP_{exc.status_code}", "error_message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """將 Pydantic 請求格式驗證失敗轉換為標準錯誤回應格式。

    不洩漏 Pydantic 內部的欄位驗證細節。
    """
    return JSONResponse(
        status_code=422,
        content={"error_code": "COMMON_422", "error_message": "請求格式驗證失敗"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """攔截所有未預期例外，記錄完整 stack trace 後回傳通用 500。

    前端只看到 "Internal Server Error"，不洩漏內部細節；
    後端 log 保留完整錯誤資訊供排查。
    AppError / HTTPException / RequestValidationError 均有專屬 handler，不會走到此處。
    """
    logger.error(
        "Unhandled exception on %s %s\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"error_code": "COMMON_500", "error_message": "Internal Server Error"},
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """健康檢查端點，含 DB 探活（SELECT 1）。DB 斷線時回傳 503。"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ok", "app": settings.APP_NAME, "db": "connected"})
    except Exception:
        logger.warning("Health check DB 探活失敗", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "error", "app": settings.APP_NAME, "db": "unreachable"})


@app.get("/api/version", response_model=VersionResponse)
async def get_version() -> VersionResponse:
    """回傳目前系統版本號（來源：pyproject.toml）。"""
    return VersionResponse(version=_APP_VERSION)


@app.get("/api/client-info", response_model=ClientInfoResponse)
async def get_client_info() -> ClientInfoResponse:
    """回傳呼叫者的連線資訊（IP + IPv4/IPv6 協定）。

    公開端點不需 JWT，回傳資訊僅含請求者自身 IP，無資訊洩漏疑慮。
    IP 由 client_ip_middleware 寫入 contextvar；is_ipv6 以「IP 字串含冒號」判斷。
    """
    ip = get_client_ip()
    return ClientInfoResponse(ip=ip, is_ipv6=":" in ip if ip else False)
