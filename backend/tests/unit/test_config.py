"""core.config 設定測試——涵蓋 #16 T001 新增之 JWT / SMTP 設定。"""

import pytest

from app.core.config import Settings, _build_settings

pytestmark = pytest.mark.unit


def test_new_settings_defaults() -> None:
    """JWT / SMTP 選填設定之預設值正確（僅提供必填欄位）。"""
    s = Settings(
        _env_file=None,  # 不讀真實 .env，確保 hermetic
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret",
    )
    assert s.JWT_ALGORITHM == "HS256"
    assert s.MAIL_HOST == ""
    assert s.MAIL_PORT == 587
    assert s.MAIL_FROM == "noreply@edms.local"
    assert s.MAIL_STARTTLS is True


def test_jwt_secret_key_is_required() -> None:
    """JWT_SECRET_KEY 無預設值、屬必填（缺少時 _build_settings 會 fail-fast）。"""
    assert Settings.model_fields["JWT_SECRET_KEY"].is_required() is True


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
