"""core.config 設定測試——涵蓋 #16 T001 新增之 JWT / SMTP 設定。"""

import pytest

from app.core.config import Settings, _build_settings

pytestmark = pytest.mark.unit


def test_new_settings_defaults() -> None:
    """JWT / SMTP 選填設定之預設值正確（僅提供必填欄位）。"""
    s = Settings(
        _env_file=None,  # 不讀真實 .env，確保 hermetic
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
    )
    assert s.JWT_ALGORITHM == "HS256"
    assert s.MAIL_HOST == ""
    assert s.MAIL_PORT == 587
    assert s.MAIL_FROM == "noreply@edms.local"
    assert s.MAIL_STARTTLS is True


def test_jwt_secret_key_is_required() -> None:
    """JWT_SECRET_KEY 無預設值、屬必填（缺少時 _build_settings 會 fail-fast）。"""
    assert Settings.model_fields["JWT_SECRET_KEY"].is_required() is True


def _settings_with_key(key: str, algorithm: str = "HS256") -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY=key,
        JWT_ALGORITHM=algorithm,
    )


def test_jwt_secret_too_short_rejected() -> None:
    """短於演算法門檻（HS256 → 32 bytes）的密鑰啟動即被擋。"""
    with pytest.raises(ValueError, match="JWT_SECRET_KEY too short"):
        _settings_with_key("short-key")


def test_jwt_secret_min_length_accepted() -> None:
    """剛好達門檻的密鑰通過。"""
    key = "x" * 32
    assert _settings_with_key(key).JWT_SECRET_KEY == key


def test_jwt_secret_length_threshold_follows_algorithm() -> None:
    """門檻依演算法而異：32 bytes 對 HS256 過關、對 HS512 不足（需 64）。"""
    key = "x" * 32
    assert _settings_with_key(key, "HS256").JWT_ALGORITHM == "HS256"
    with pytest.raises(ValueError, match="requires >= 64 bytes"):
        _settings_with_key(key, "HS512")


def test_build_settings_rejects_short_key_as_invalid() -> None:
    """短密鑰經 _build_settings 轉為安全 RuntimeError（歸為 invalid，不回顯密鑰值）。"""
    with pytest.raises(RuntimeError) as exc_info:
        _build_settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="weak",
        )
    message = str(exc_info.value)
    assert "invalid environment variables" in message
    assert "JWT_SECRET_KEY" in message
    assert "weak" not in message  # 不回顯密鑰值


def test_build_settings_fail_fast_masks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少必填設定時 _build_settings 拋 RuntimeError，訊息僅含欄位名稱、不回顯機密值。"""
    # 移除 conftest 以 setdefault 注入的必填變數，模擬「完全未設定」情境
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        _build_settings(_env_file=None)  # 不讀 .env，強制 env 缺漏

    message = str(exc_info.value)
    assert "missing required environment variables" in message
    assert "JWT_SECRET_KEY" in message
    assert "DATABASE_URL" in message
    # 確認錯誤訊息不回顯任何機密值（避免 boot log 洩漏）
    assert "dev-only" not in message
    assert "test-secret" not in message
