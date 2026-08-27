import asyncio
import logging
import tomllib
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.client_ip import resolve_client_ip
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.exceptions import AppError
from app.core.log_redaction import format_exception_for_log
from app.core.password_hashing import shutdown as shutdown_password_executor
from app.core.password_hashing import warm_up as warm_up_password_backend
from app.core.request_context import get_client_ip, set_client_ip
from app.dm.bootstrap import register_dm_module
from app.dm.dashboard.router import router as dm_dashboard_router
from app.dm.detail.router import router as dm_detail_router
from app.dm.editor.router import router as dm_editor_router
from app.dm.library.router import router as dm_library_router
from app.dm.obsolete.router import router as dm_obsolete_router
from app.dm.personal.router import router as dm_personal_router
from app.dm.review.router import router as dm_review_router
from app.dp.audit.router import router as dp_audit_router
from app.dp.notify.mailer import SmtpMailer
from app.dp.notify.router import router as dp_templates_router
from app.dp.notify.worker import run_forever
from app.dp.params.router import router as dp_params_router
from app.dp.roles.router import router as dp_roles_router
from app.dp.schedules.router import router as dp_schedule_router
from app.dp.schedules.scheduler import shutdown_scheduler, start_scheduler
from app.dp.user.router import router as dp_user_router
from app.dp.users.router import router as dp_users_router
from app.et.bootstrap import register_et_module
from app.et.course.router import router as et_course_router
from app.et.material.router import router as et_material_router
from app.et.quiz.router import router as et_quiz_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    """啟停常駐發信 worker（SRVDP002 outbox 消費者）與排程引擎（US11，APScheduler）。

    兩者皆 lifespan 背景元件、互不依賴：worker 消 DP_EMAIL_LOG、scheduler 依 DP_SCHEDULE 觸發 job。
    """
    # 密碼運算後端暖機（#214）：讓 passlib 的惰性初始化在單執行緒下完成，避免多 worker
    # 首呼的競態，並把它已知的版本偵測 traceback 落在啟動階段而非第一個使用者登入時。
    await warm_up_password_backend()
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_forever(SmtpMailer(), stop_event))
    scheduler = await start_scheduler()
    try:
        yield
    finally:
        # 先關排程引擎（等當前 job 跑完），再請 worker 優雅收斂（跑完當前 cycle 並 commit），
        # 逾時才強制取消——避免在「已透過 SMTP 寄出、尚未 commit」的空窗被 cancel 導致 rollback 後重送。
        await shutdown_scheduler(scheduler)
        shutdown_password_executor()
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

# 業務模組 router
app.include_router(dp_user_router)
app.include_router(dp_users_router)
app.include_router(dp_params_router)
app.include_router(dp_roles_router)
app.include_router(dp_templates_router)
app.include_router(dp_audit_router)
app.include_router(dp_schedule_router)
app.include_router(dm_dashboard_router)
app.include_router(dm_library_router)
app.include_router(dm_detail_router)
app.include_router(dm_editor_router)
app.include_router(dm_review_router)
app.include_router(dm_obsolete_router)
app.include_router(dm_personal_router)
app.include_router(et_course_router)
app.include_router(et_material_router)
app.include_router(et_quiz_router)

# DM 模組啟動接線：註冊 DM 判定閘 checker（§1 / §4），供 DP 入口頁 / 後台呼叫
register_dm_module()

# ET 模組啟動接線（#185）：註冊四個聚合閘 checker / provider（§1~§4）。
# ⚠️ 本呼叫是 DP #113（真授權閘掛 router）之解鎖條件——閘為 fail-closed，
# 無模組註冊時會使整個 DP 後台 403。與業務 router 之 include 相互獨立：
# 閘註冊是「ET 這個模組存在」的宣告，router 則是各功能的端點掛載。
register_et_module()


@app.middleware("http")
async def client_ip_middleware(request: Request, call_next):
    """每個 request 進入時判定 client IP 並記錄至 contextvars。

    safe-by-default（#23）：預設不採信可偽造的 X-Forwarded-For，一律用連線對端；
    僅在部署方設定 TRUSTED_PROXY_COUNT 時，才採信我方代理鏈追加的段落。
    判定邏輯見 app/core/client_ip.resolve_client_ip；設定於每個 request 讀取，
    速率限制與稽核日誌共用此 contextvar，故兩者取得的 IP 恆一致。
    """
    client_ip = resolve_client_ip(
        peer=request.client.host if request.client else None,
        # 依 RFC 7230 §3.2.2：同名 header 多次出現等同以逗號依序併為單一清單。
        # 不可用 headers.get()（只取第一個出現值）——攻擊者另送一個 X-Forwarded-For
        # 即可讓代理追加的段落被忽略，繞過固定段數判定。
        forwarded_for=", ".join(request.headers.getlist("X-Forwarded-For")) or None,
        trusted_proxy_count=settings.TRUSTED_PROXY_COUNT,
    )
    set_client_ip(client_ip)
    try:
        return await call_next(request)
    finally:
        set_client_ip(None)


# 各業務模組的 router 於後續 task 開發時在此 include。


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """將 AppError 統一轉換為標準錯誤回應格式。

    回傳格式：{"error_code": "...", "error_message": "..."}；限流 / 冷卻類 429 另帶 retry_after。
    debug log 保留完整錯誤細節供後端排查，不對外暴露。
    """
    logger.debug("AppError %s %s: [%s] %s", request.method, request.url.path, exc.error_code, exc.detail)
    content: dict[str, object] = {"error_code": exc.error_code, "error_message": exc.detail}
    if exc.retry_after is not None:
        content["retry_after"] = exc.retry_after
    return JSONResponse(status_code=exc.status_code, content=content)


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
    """將 Pydantic 請求格式驗證失敗轉換為標準錯誤回應格式，並**指出是哪些欄位**。

    ## 為何改為回傳欄位名（2026-08-27）

    原本一律回「請求格式驗證失敗」，理由是「不洩漏 Pydantic 內部的欄位驗證細節」。
    但那讓所有驗證失敗長得一模一樣——使用者（與排查的人）無從知道這次錯在哪。

    真正不該外洩的是 **`input`（使用者送出的值）**：驗證失敗的欄位可能正是密碼、
    Email 等敏感內容，回傳等於把它寫進前端畫面與瀏覽器 log。**欄位名稱則不然**
    ——它本來就印在 OpenAPI 文件上，是公開的 API 契約。

    故此處只取 `loc` 的最後一段（欄位名），**不取 `input`、不取 pydantic 的原始
    `msg`**（後者是英文且可能帶出正則式等實作細節）。

    `fields` 為附加欄位，既有前端忽略它不會壞；需要逐欄標記的畫面才取用。

    > 前端仍應在送出前自行驗證——這裡是最後一道網，不是主要的使用者回饋管道。
    """
    fields = sorted({str(err["loc"][-1]) for err in exc.errors() if err.get("loc")})
    detail = f"以下欄位不符規定：{'、'.join(fields)}" if fields else "請求格式不符規定"
    return JSONResponse(
        status_code=422,
        content={"error_code": "COMMON_422", "error_message": detail, "fields": fields},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """攔截所有未預期例外，記錄去識別化後的例外摘要與堆疊後回傳通用 500。

    前端只看到 "Internal Server Error"，不洩漏內部細節。
    後端 log 保留例外型別、遮罩後訊息與堆疊位置供排查；刻意不用 traceback.format_exc()
    ——SQLAlchemy StatementError 的訊息含 SQL 與綁定參數，會把個資寫進 log（#123），
    改由 app/core/log_redaction.format_exception_for_log 去識別化。
    AppError / HTTPException / RequestValidationError 均有專屬 handler，不會走到此處。
    """
    logger.error(
        "Unhandled exception on %s %s\n%s",
        request.method,
        request.url.path,
        format_exception_for_log(exc),
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
