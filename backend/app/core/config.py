import ipaddress
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# HMAC 密鑰最小長度（bytes）對齊 RFC 7518 §3.2 各演算法輸出長度，防過短/未替換密鑰。
_MIN_JWT_KEY_BYTES = {"HS256": 32, "HS384": 48, "HS512": 64}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 應用程式
    APP_NAME: str = "EDMS"
    DEBUG: bool = False

    # CORS
    # dev 預設對齊前端 dev server（vite.config 用 5174，刻意與同機 TBMS 5173 錯開）
    CORS_ORIGINS: str = "http://localhost:5174"

    # 前端公開 base URL（組信中連結，如密碼重設頁）；因部署環境而異，dev 預設對齊前端 dev server（5174）
    FRONTEND_BASE_URL: str = "http://localhost:5174"

    # 反向代理與 client IP（#23）——應用前方「我方掌控」的反向代理台數（含最靠近 app 的那一台）。
    # 0（預設）表示應用直接對外：完全忽略可偽造的 X-Forwarded-For，一律用連線對端 IP。
    # 設 >0 才從 XFF 右數第 N 段取 client IP（見 app/core/client_ip.py 與
    # docs/ref/deployment-client-ip.md）。誤設過大只會退回連線對端，不會採信偽造值。
    TRUSTED_PROXY_COUNT: int = Field(default=0, ge=0, le=8)

    # 資料庫
    DATABASE_URL: str

    # 連線池
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60)

    # 認證（簡單 JWT）
    # 各環境獨立產生、不進 git；缺少時 fail-fast（見 _build_settings）。
    # access token TTL / 閒置逾時 / 換發上限等存 DP_PARAM（`JWT` 參數，見
    # docs/specs/dp/data-model.md），非環境變數。
    JWT_SECRET_KEY: str
    # 限對稱演算法（EDMS 採簡單對稱 JWT，見 research §2）；收斂為 Literal 使誤設
    # 非對稱 / none 於啟動即被 Pydantic 擋下，杜絕 algorithm confusion 隱患。
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"

    # 寄信（SMTP）— 由平台發信引擎（#16 T018 起）使用；
    # 未設定時不影響應用啟動，實際寄送於發信 task 接上。
    MAIL_SERVER: str = ""
    MAIL_PORT: int = Field(default=587, ge=1, le=65535)
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "noreply@edms.local"
    MAIL_STARTTLS: bool = True
    # implicit TLS（如埠 465）；與 STARTTLS 互斥，兩者不可同時 true
    MAIL_SSL_TLS: bool = False
    # 測試 / E2E 跳過實際寄送（信件仍寫 outbox、不連 SMTP）
    MAIL_SUPPRESS_SEND: bool = False

    # 邀請重寄冷卻（US4 dp-users，#72）——同一筆邀請（invite_id）重寄的最小間隔秒數，
    # 防對單一受邀信箱短時間反覆轟炸。刻意不設操作者總量限流（批次為多人建帳號屬正常，見 router）。
    # 走 config（deploy 時可調）而非 DP_PARAM，貼合「依部署環境 / 寄信額度定」語意且免 migration。
    INVITE_RESEND_COOLDOWN_SEC: int = Field(default=600, ge=0)

    # DM 文件上傳落盤根目錄（US5）——上傳之檔案位元組寫入此根下、以系統產生之 FILE_ID 命名，
    # DB 存絕對 FILE_PATH（os.path.abspath，見 dm/editor/storage.py）。讀寫端皆經 dm/document/file_paths
    # 之 storage-root 圍籬（#160）。走 config（依部署環境定；正式建議設絕對路徑、可換物件儲存）。
    DM_FILE_STORAGE_ROOT: str = "./var/dm_files"

    @model_validator(mode="after")
    def _validate_jwt_secret_strength(self) -> "Settings":
        """依所選演算法強制 HMAC 密鑰最小長度，啟動即擋弱 / 未替換的預設密鑰。

        缺值已由必填 fail-fast 擋下；本驗證補「弱密鑰被靜默接受」缺口
        （PyJWT 對過短密鑰僅發 warning、仍照常簽發）。訊息僅含欄位名與門檻，
        不 echo 密鑰值（沿用本檔不洩漏機密原則；_build_settings 會歸為 invalid）。
        """
        min_bytes = _MIN_JWT_KEY_BYTES[self.JWT_ALGORITHM]
        if len(self.JWT_SECRET_KEY.encode("utf-8")) < min_bytes:
            raise ValueError(f"JWT_SECRET_KEY too short for {self.JWT_ALGORITHM}: requires >= {min_bytes} bytes")
        return self

    @model_validator(mode="after")
    def _validate_mail_tls(self) -> "Settings":
        """MAIL 傳輸層 TLS 設定檢查：

        1. STARTTLS 與 SSL_TLS 互斥（STARTTLS 為明文升級、SSL_TLS 為 implicit TLS）。
        2. production（非 DEBUG、非 SUPPRESS_SEND）且已設定 MAIL_SERVER 時，至少一種 TLS 需啟用，
           禁止明文 SMTP 傳輸（帳密與信件內容明文上線）。
        """
        if self.MAIL_STARTTLS and self.MAIL_SSL_TLS:
            raise ValueError("MAIL_STARTTLS 與 MAIL_SSL_TLS 不可同時為 true")
        if (
            self.MAIL_SERVER
            and not self.DEBUG
            and not self.MAIL_SUPPRESS_SEND
            and not (self.MAIL_STARTTLS or self.MAIL_SSL_TLS)
        ):
            raise ValueError(
                "production 已設定 MAIL_SERVER 時，MAIL_STARTTLS 或 MAIL_SSL_TLS 至少一為 true（禁明文 SMTP）"
            )
        return self

    @model_validator(mode="after")
    def _validate_frontend_base_url(self) -> "Settings":
        """production（非 DEBUG）護欄：FRONTEND_BASE_URL 不得為空、不得指向 localhost / 127.0.0.1。

        此 URL 用於組信中連結（密碼重設 / 註冊驗證 / 帳號啟用邀請等，見 forgot / register /
        users service）。prod 忘設正式網域時，localhost 預設會靜默寄出指向使用者本機的死連結；
        此處 fail-loud，啟動即擋。dev（DEBUG=true）維持 localhost 便利。

        以解析 host（轉小寫）精確比對：避免大小寫（`HTTP://LOCALHOST`）漏擋，
        亦避免正式網域含 "localhost" 子字串（如 my-localhost-proxy.example.com）被誤擋。
        可解析為 IP 的 host 以 `ipaddress.is_loopback` 判定，涵蓋 127.0.0.0/8 與 IPv6 `::1`。
        """
        if not self.DEBUG:
            raw = self.FRONTEND_BASE_URL.strip()
            host = (urlparse(raw).hostname or "").lower()
            is_loopback = host == "localhost" or host.endswith(".localhost")
            if not is_loopback and host:
                try:
                    is_loopback = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    is_loopback = False  # 非 IP 字面（正式網域）→ 交由上面的名稱判定
            # host 解析不到（缺 scheme 等）時退回整串小寫子字串比對，避免漏擋
            if not host and raw:
                low = raw.lower()
                is_loopback = "localhost" in low or "127.0.0.1" in low or "::1" in low
            if not raw or is_loopback:
                raise ValueError(
                    "FRONTEND_BASE_URL 在 production（DEBUG=false）不得為空或指向 localhost / 127.0.0.1；"
                    "請於 .env 設為正式前端網域（見 backend/.env.example）"
                )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        """將逗號分隔的 CORS_ORIGINS 字串解析為 list，自動去除前後空白。

        禁止使用 wildcard "*"，因為本專案啟用 allow_credentials=True。
        """
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError(
                "CORS_ORIGINS 不可包含 '*'，因為已啟用 allow_credentials=True。\n"
                "請明確列出允許的 origin，例如：http://localhost:5174,https://edms.example.com"
            )
        return origins


def _build_settings(**kwargs: Any) -> Settings:
    """載入 Settings，將 Pydantic ValidationError 轉為安全的 RuntimeError。

    Pydantic 原生 ValidationError 的 traceback 會在 input_value 中 echo
    所有已讀入的環境變數（未來含機密）；若 boot log 被 systemd / Docker / Sentry
    收集會造成機密洩漏。本 helper 捕捉 ValidationError 並重拋只含欄位名稱的
    RuntimeError，並以 `from None` 丟棄原始 cause 避免 chained traceback 再次洩漏。

    kwargs 透傳給 Settings()（例如 _env_file=None 禁用 .env 讀取，測試用）。
    """
    try:
        return Settings(**kwargs)
    except ValidationError as exc:
        missing = [".".join(str(part) for part in err["loc"]) for err in exc.errors() if err["type"] == "missing"]
        # model 級 validator（如 JWT 密鑰長度）之 loc 為空，退回用 err["msg"]（我方 validator
        # 訊息僅含欄位名與門檻、不含值），確保運維看得到是哪個設定出錯；仍不讀 err["input"]（含機密）。
        invalid = [
            (".".join(str(part) for part in err["loc"]) or err["msg"])
            for err in exc.errors()
            if err["type"] != "missing"
        ]
        details: list[str] = []
        if missing:
            details.append(f"missing required environment variables: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid environment variables: {', '.join(invalid)}")
        raise RuntimeError(
            "Application configuration error — " + "; ".join(details) + ". See backend/.env.example for reference."
        ) from None


settings = _build_settings()
