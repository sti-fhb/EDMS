from typing import Any, Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    MAIL_HOST: str = ""
    MAIL_PORT: int = Field(default=587, ge=1, le=65535)
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "noreply@edms.local"
    MAIL_STARTTLS: bool = True

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
        invalid = [".".join(str(part) for part in err["loc"]) for err in exc.errors() if err["type"] != "missing"]
        details: list[str] = []
        if missing:
            details.append(f"missing required environment variables: {', '.join(missing)}")
        if invalid:
            details.append(f"invalid environment variables: {', '.join(invalid)}")
        raise RuntimeError(
            "Application configuration error — " + "; ".join(details) + ". See backend/.env.example for reference."
        ) from None


settings = _build_settings()
