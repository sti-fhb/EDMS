from typing import Any, Literal

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
    CORS_ORIGINS: str = "http://localhost:5173"

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

    @property
    def cors_origins_list(self) -> list[str]:
        """將逗號分隔的 CORS_ORIGINS 字串解析為 list，自動去除前後空白。

        禁止使用 wildcard "*"，因為本專案啟用 allow_credentials=True。
        """
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError(
                "CORS_ORIGINS 不可包含 '*'，因為已啟用 allow_credentials=True。\n"
                "請明確列出允許的 origin，例如：http://localhost:5173,https://edms.example.com"
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
