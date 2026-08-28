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
        DEBUG=True,  # dev context：允許 FRONTEND_BASE_URL 預設 localhost（見 _validate_frontend_base_url）
    )
    assert s.JWT_ALGORITHM == "HS256"
    assert s.MAIL_SERVER == ""
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
        DEBUG=True,  # 聚焦 JWT 驗證，dev context 免受 FRONTEND_BASE_URL prod 護欄干擾
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


def test_mail_starttls_and_ssl_tls_mutually_exclusive() -> None:
    """MAIL_STARTTLS 與 MAIL_SSL_TLS 不可同時 true。"""
    with pytest.raises(ValueError, match="不可同時"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            MAIL_STARTTLS=True,
            MAIL_SSL_TLS=True,
        )


def test_mail_plaintext_rejected_in_production() -> None:
    """production 已設 MAIL_SERVER 但兩種 TLS 皆關 → 拒絕（禁明文 SMTP）。"""
    with pytest.raises(ValueError, match="至少一為 true"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            DEBUG=False,
            FRONTEND_BASE_URL="https://edms.example.com",  # 聚焦 MAIL 明文檢查，避開 prod frontend 護欄
            MAIL_SERVER="smtp.example.com",
            MAIL_STARTTLS=False,
            MAIL_SSL_TLS=False,
        )


def test_mail_plaintext_allowed_when_suppress_send() -> None:
    """MAIL_SUPPRESS_SEND（測試 / E2E）時允許無 TLS（不實際連線）。"""
    s = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=False,
        FRONTEND_BASE_URL="https://edms.example.com",  # DEBUG=false 下需正式網域，避開 prod frontend 護欄
        TRUSTED_PROXY_COUNT=0,  # DEBUG=false 下需明示（見 _validate_trusted_proxy_count_explicit）
        DM_FILE_STORAGE_ROOT="/srv/edms/dm_files",  # DEBUG=false 下須絕對路徑（見 _validate_storage_roots_absolute）
        ET_VIDEO_STORAGE_ROOT="/srv/edms/et_videos",
        MAIL_SERVER="smtp.example.com",
        MAIL_STARTTLS=False,
        MAIL_SSL_TLS=False,
        MAIL_SUPPRESS_SEND=True,
    )
    assert s.MAIL_SUPPRESS_SEND is True


def _settings_with_frontend(url: str, *, debug: bool) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=debug,
        FRONTEND_BASE_URL=url,
        TRUSTED_PROXY_COUNT=0,  # 聚焦 FRONTEND_BASE_URL 驗證，避開 production 明示設定護欄
        DM_FILE_STORAGE_ROOT="/srv/edms/dm_files",  # 同上，避開 storage root 絕對路徑護欄
        ET_VIDEO_STORAGE_ROOT="/srv/edms/et_videos",
    )


def test_frontend_base_url_localhost_rejected_in_production() -> None:
    """production（DEBUG=false）時 FRONTEND_BASE_URL 指向 localhost → 拒絕（防組信寄出指向使用者本機的死連結）。"""
    with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
        _settings_with_frontend("http://localhost:5174", debug=False)


def test_frontend_base_url_loopback_ip_rejected_in_production() -> None:
    """production 時指向 127.0.0.1 亦拒絕。"""
    with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
        _settings_with_frontend("http://127.0.0.1:5174", debug=False)


def test_frontend_base_url_empty_rejected_in_production() -> None:
    """production 時空字串拒絕（忘設正式網域）。"""
    with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
        _settings_with_frontend("", debug=False)


def test_frontend_base_url_uppercase_localhost_rejected_in_production() -> None:
    """大小寫不敏感：HTTP://LOCALHOST 於 production 仍被擋（解析 host 後小寫比對）。"""
    with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
        _settings_with_frontend("HTTP://LOCALHOST:5174", debug=False)


def test_frontend_base_url_ipv6_loopback_rejected_in_production() -> None:
    """IPv6 loopback [::1] 於 production 被擋（ipaddress.is_loopback 判定）。"""
    with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
        _settings_with_frontend("http://[::1]:5174", debug=False)


def test_frontend_base_url_domain_containing_localhost_allowed() -> None:
    """正式網域名稱恰含 'localhost' 子字串（非 loopback host）不應誤擋。"""
    s = _settings_with_frontend("https://my-localhost-proxy.example.com", debug=False)
    assert s.FRONTEND_BASE_URL == "https://my-localhost-proxy.example.com"


def test_frontend_base_url_localhost_allowed_in_debug() -> None:
    """dev（DEBUG=true）保留 localhost 便利，不擋。"""
    s = _settings_with_frontend("http://localhost:5174", debug=True)
    assert "localhost" in s.FRONTEND_BASE_URL


def test_frontend_base_url_production_domain_accepted() -> None:
    """production 設正式網域 → 通過。"""
    s = _settings_with_frontend("https://edms.example.com", debug=False)
    assert s.FRONTEND_BASE_URL == "https://edms.example.com"


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


def _settings_for_proxy_count(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://t:t@localhost/t",
        "JWT_SECRET_KEY": "unit-test-secret-key-at-least-32-bytes-long",
        "FRONTEND_BASE_URL": "https://edms.example.com",
        # 聚焦 TRUSTED_PROXY_COUNT 驗證，避開 storage root 絕對路徑護欄（#233）
        "DM_FILE_STORAGE_ROOT": "/srv/edms/dm_files",
        "ET_VIDEO_STORAGE_ROOT": "/srv/edms/et_videos",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


def test_trusted_proxy_count_required_in_production() -> None:
    """production 未明示 TRUSTED_PROXY_COUNT → 啟動即擋。

    預設 0 在「反向代理 → 應用」部署下會靜默塌縮成「全站共用一個限流桶 +
    稽核 SOURCE_IP 全為代理 IP」，無任何錯誤訊息，故強迫部署方表態。
    """
    with pytest.raises(ValueError, match="TRUSTED_PROXY_COUNT"):
        _settings_for_proxy_count(DEBUG=False)


def test_trusted_proxy_count_explicit_zero_accepted_in_production() -> None:
    """production 明示設 0（應用直接對外）→ 通過。"""
    s = _settings_for_proxy_count(DEBUG=False, TRUSTED_PROXY_COUNT=0)
    assert s.TRUSTED_PROXY_COUNT == 0


def test_trusted_proxy_count_not_required_in_debug() -> None:
    """dev（DEBUG=true）維持免設定便利，預設 0＝忽略 XFF。"""
    s = _settings_for_proxy_count(DEBUG=True)
    assert s.TRUSTED_PROXY_COUNT == 0


def test_trusted_proxy_count_upper_bound() -> None:
    """上限 8：明顯誤設（如把毫秒數填進來）於啟動即擋。"""
    with pytest.raises(ValueError):
        _settings_for_proxy_count(DEBUG=True, TRUSTED_PROXY_COUNT=99)


# ── storage root production 護欄（#233 AC8）──────────────────────
# 兩個落盤根的預設值是相對路徑（./var/dm_files、./var/et_videos），storage_root() 以
# os.path.realpath 解析 → 結果依 process 的工作目錄而定。同一份設定從不同目錄啟動會
# 得到不同的 root。#160 close 留言已記為 Security LOW-4（當時只留建議、未加護欄）；
# FILE_PATH 改存相對路徑後，root 設錯的後果更集中（所有檔案一起讀不到），故補上護欄。


def _prod_settings(**overrides) -> Settings:
    """建構一份通過其他 prod 護欄的 Settings，好讓測試聚焦在 storage root。"""
    base = dict(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=False,
        FRONTEND_BASE_URL="https://edms.example.com",
        TRUSTED_PROXY_COUNT=0,
        DM_FILE_STORAGE_ROOT="/srv/edms/dm_files",
        ET_VIDEO_STORAGE_ROOT="/srv/edms/et_videos",
    )
    base.update(overrides)
    return Settings(**base)


def test_prod_absolute_storage_roots_accepted() -> None:
    """兩個 root 皆為絕對路徑時 production 正常啟動。"""
    s = _prod_settings()
    assert s.DM_FILE_STORAGE_ROOT == "/srv/edms/dm_files"


@pytest.mark.parametrize("field", ["DM_FILE_STORAGE_ROOT", "ET_VIDEO_STORAGE_ROOT"])
def test_prod_relative_storage_root_rejected(field: str) -> None:
    """production 下相對 root 一律擋，且錯誤訊息指名是哪一個變數。"""
    with pytest.raises(ValueError) as e:
        _prod_settings(**{field: "./var/whatever"})
    assert field in str(e.value)


def test_prod_default_storage_root_rejected() -> None:
    """預設值本身就是相對路徑，未明示設定即應擋下（防「忘了設」靜默塌縮）。"""
    base = dict(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=False,
        FRONTEND_BASE_URL="https://edms.example.com",
        TRUSTED_PROXY_COUNT=0,
    )
    with pytest.raises(ValueError):
        Settings(**base)


def test_dev_relative_storage_root_allowed() -> None:
    """DEBUG=true 之本機開發不受影響——相對 root 是 dev 的便利預設。"""
    s = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=True,
    )
    assert s.DM_FILE_STORAGE_ROOT == "./var/dm_files"
    assert s.ET_VIDEO_STORAGE_ROOT == "./var/et_videos"
