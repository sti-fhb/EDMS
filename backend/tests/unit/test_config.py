"""core.config 設定測試——涵蓋 #16 T001 新增之 JWT / SMTP 設定。"""

import ast
import os
from pathlib import Path

import pytest

from app.core.config import Settings, _build_settings

pytestmark = pytest.mark.unit

# production 護欄要求絕對路徑，且 Windows 另需磁碟機（見 _validate_storage_roots_absolute）。
# 測試值依平台給，否則同一份測試在 Windows / Linux 其中一邊必然失敗。
_ABS_DM_ROOT = r"C:\srv\edms\dm_files" if os.name == "nt" else "/srv/edms/dm_files"
_ABS_ET_ROOT = r"C:\srv\edms\et_videos" if os.name == "nt" else "/srv/edms/et_videos"


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


def test_mail_plaintext_allowed_in_production() -> None:
    """production 已設 MAIL_SERVER、兩種 TLS 皆關（埠 25 不加密）→ 可正常啟動（#585）。

    院內郵件主機只開埠 25、不加密、以 IP 授權，與 TBMS 同組設定；加密方式由部署端依郵件主機決定。
    MAIL_SUPPRESS_SEND 刻意設 false——它為 true 時本來就放行，設了等於沒驗到。
    """
    s = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=False,
        FRONTEND_BASE_URL="https://edms.example.com",  # DEBUG=false 下需正式網域，避開 prod frontend 護欄
        TRUSTED_PROXY_COUNT=0,  # DEBUG=false 下需明示（見 _validate_trusted_proxy_count_explicit）
        DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,  # DEBUG=false 下須絕對路徑（見 _validate_storage_roots_absolute）
        ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
        MAIL_SERVER="smtp.example.com",
        MAIL_PORT=25,
        MAIL_STARTTLS=False,
        MAIL_SSL_TLS=False,
        MAIL_SUPPRESS_SEND=False,
    )
    assert s.DEBUG is False
    assert (s.MAIL_STARTTLS, s.MAIL_SSL_TLS) == (False, False)


def _settings_with_frontend(url: str, *, debug: bool) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=debug,
        FRONTEND_BASE_URL=url,
        TRUSTED_PROXY_COUNT=0,  # 聚焦 FRONTEND_BASE_URL 驗證，避開 production 明示設定護欄
        DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,  # 同上，避開 storage root 絕對路徑護欄
        ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
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
        "DM_FILE_STORAGE_ROOT": _ABS_DM_ROOT,
        "ET_VIDEO_STORAGE_ROOT": _ABS_ET_ROOT,
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


def _settings_for_seed(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://t:t@localhost/t",
        "JWT_SECRET_KEY": "unit-test-secret-key-at-least-32-bytes-long",
        "FRONTEND_BASE_URL": "https://edms.example.com",
        # 聚焦 SEED_DEMO_ACCOUNTS 預設值，避開其餘 production 護欄
        "TRUSTED_PROXY_COUNT": 0,
        "DM_FILE_STORAGE_ROOT": _ABS_DM_ROOT,
        "ET_VIDEO_STORAGE_ROOT": _ABS_ET_ROOT,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def _no_seed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """「未設定」須連環境變數一併排除——`_env_file=None` 只隔離 .env 檔，不隔離 os.environ。"""
    monkeypatch.delenv("SEED_DEMO_ACCOUNTS", raising=False)


@pytest.mark.usefixtures("_no_seed_env")
def test_seed_demo_accounts_defaults_false_in_production() -> None:
    """正式模式未設定 → 預設不種示範帳號（不沿用欄位預設 true）。"""
    s = _settings_for_seed(DEBUG=False)
    assert s.SEED_DEMO_ACCOUNTS is False


def test_seed_demo_accounts_explicit_true_honored_in_production() -> None:
    """正式模式明示 true → 依設定值種入。"""
    s = _settings_for_seed(DEBUG=False, SEED_DEMO_ACCOUNTS=True)
    assert s.SEED_DEMO_ACCOUNTS is True


def test_seed_demo_accounts_env_true_honored_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """部署以環境變數 / env_file 注入（非建構參數），該來源同樣算已設定。"""
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    s = _settings_for_seed(DEBUG=False)
    assert s.SEED_DEMO_ACCOUNTS is True


@pytest.mark.usefixtures("_no_seed_env")
def test_seed_demo_accounts_defaults_true_in_debug() -> None:
    """dev（DEBUG=true）未設定 → 維持預設種入，供本機手動驗證登入。"""
    s = _settings_for_seed(DEBUG=True)
    assert s.SEED_DEMO_ACCOUNTS is True


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
        DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,
        ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
    )
    base.update(overrides)
    return Settings(**base)


def test_prod_absolute_storage_roots_accepted() -> None:
    """兩個 root 皆為絕對路徑時 production 正常啟動。"""
    s = _prod_settings()
    assert s.DM_FILE_STORAGE_ROOT == _ABS_DM_ROOT


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


def test_prod_storage_root_with_surrounding_whitespace_rejected() -> None:
    """帶前後空白之相對路徑不得被放行（#233 security review MEDIUM-1）。

    原缺陷：檢查時 `.strip()` 但沒寫回欄位，於是護欄看乾淨值、storage_root() 用原值，
    `realpath("  ./var  ")` 接到 CWD 底下——護欄放行了它本來要擋的失敗模式且完全無聲。
    python-dotenv 對引號內空白原樣保留（`ROOT="  x  "`），非理論情境。
    """
    with pytest.raises(ValueError) as e:
        _prod_settings(DM_FILE_STORAGE_ROOT="  ./var/dm_files  ")
    assert "DM_FILE_STORAGE_ROOT" in str(e.value)


def test_storage_root_whitespace_is_stripped_into_the_stored_value() -> None:
    """空白須在賦值前正規化——「被檢查的值」與「被使用的值」必須是同一個。"""
    s = _prod_settings(DM_FILE_STORAGE_ROOT=f"  {_ABS_DM_ROOT}  ")
    assert s.DM_FILE_STORAGE_ROOT == _ABS_DM_ROOT


@pytest.mark.skipif(os.name != "nt", reason="磁碟機語意僅 Windows 適用")
def test_prod_driveless_absolute_root_rejected_on_windows() -> None:
    """Windows：無磁碟機之絕對路徑依當前磁碟機解析，仍屬靜默飄移（LOW-2）。

    `os.path.isabs("/srv/dm")` 在 nt 為 True，但 `realpath` 會解析成 `C:\\srv\\dm`——
    從 D: 啟動即得到不同 root，正是本護欄要擋的那種飄移。故此處刻意不用 `_ABS_DM_ROOT`。
    """
    with pytest.raises(ValueError) as e:
        _prod_settings(DM_FILE_STORAGE_ROOT="/srv/edms/dm_files")
    assert "磁碟機" in str(e.value)


@pytest.mark.skipif(os.name != "nt", reason="UNC 語意僅 Windows 適用")
def test_prod_unc_root_accepted_on_windows() -> None:
    """UNC 路徑有明確主機 / 共享，不受當前磁碟機影響，不應被磁碟機檢查誤擋。"""
    unc_dm = "\\\\fileserver\\edms\\dm_files"
    s = _prod_settings(
        DM_FILE_STORAGE_ROOT=unc_dm,
        ET_VIDEO_STORAGE_ROOT="\\\\fileserver\\edms\\et_videos",
    )
    assert s.DM_FILE_STORAGE_ROOT == unc_dm


# --- SCAN_ACCESS_TTL_MIN（院內資安檢測期間的 access token 時效覆寫）---


def _settings_with_scan_ttl(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://t:t@localhost/t",
        "JWT_SECRET_KEY": "unit-test-secret-key-at-least-32-bytes-long",
        "DEBUG": True,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


def test_scan_access_ttl_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定時為 None——代表不覆寫，access token TTL 照舊讀 DP_PARAM。"""
    monkeypatch.delenv("SCAN_ACCESS_TTL_MIN", raising=False)
    assert _settings_with_scan_ttl().SCAN_ACCESS_TTL_MIN is None


@pytest.mark.parametrize("value", [1, 600, 720])
def test_scan_access_ttl_accepts_values_in_range(value: int) -> None:
    """範圍內（1～720 分鐘）的值照收；600 為 TBMS scan-mode 實際寫入值。"""
    assert _settings_with_scan_ttl(SCAN_ACCESS_TTL_MIN=value).SCAN_ACCESS_TTL_MIN == value


@pytest.mark.parametrize("value", [0, -1, 721])
def test_scan_access_ttl_out_of_range_fails_startup(value: int) -> None:
    """超出範圍經 _build_settings 轉為啟動失敗，訊息點名欄位。"""
    with pytest.raises(RuntimeError) as exc_info:
        _build_settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            DEBUG=True,
            SCAN_ACCESS_TTL_MIN=value,
        )
    message = str(exc_info.value)
    assert "invalid environment variables" in message
    assert "SCAN_ACCESS_TTL_MIN" in message


# --- MAIL_WORKER_POLL_INTERVAL_SECONDS（發信 worker 輪距；E2E 縮短以免每封信等滿 60 秒，#57）---


def test_mail_worker_poll_interval_defaults_to_60(monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定時維持 60 秒——與 DP_PARAM MAIL.RATE_PER_MIN 的「每分鐘」語意對齊。"""
    monkeypatch.delenv("MAIL_WORKER_POLL_INTERVAL_SECONDS", raising=False)
    assert _settings_with_scan_ttl().MAIL_WORKER_POLL_INTERVAL_SECONDS == 60


def test_mail_worker_poll_interval_short_value_allowed_in_debug() -> None:
    """dev / CI / E2E（DEBUG=true）可縮短輪距。"""
    assert _settings_with_scan_ttl(MAIL_WORKER_POLL_INTERVAL_SECONDS=1).MAIL_WORKER_POLL_INTERVAL_SECONDS == 1


@pytest.mark.parametrize("value", [0, -1, 3601])
def test_mail_worker_poll_interval_out_of_range_fails_startup(value: int) -> None:
    """超出 1～3600 秒經 _build_settings 轉為啟動失敗，訊息點名欄位。"""
    with pytest.raises(RuntimeError) as exc_info:
        _build_settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            DEBUG=True,
            MAIL_WORKER_POLL_INTERVAL_SECONDS=value,
        )
    assert "MAIL_WORKER_POLL_INTERVAL_SECONDS" in str(exc_info.value)


def test_mail_worker_poll_interval_below_60_rejected_in_production() -> None:
    """production 不得低於 60 秒：worker 每輪最多寄 RATE_PER_MIN 封，輪距縮短等於把發信速率上限放大。"""
    with pytest.raises(ValueError, match="MAIL_WORKER_POLL_INTERVAL_SECONDS"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            DEBUG=False,
            FRONTEND_BASE_URL="https://edms.example.com",
            TRUSTED_PROXY_COUNT=0,
            DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,
            ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
            MAIL_WORKER_POLL_INTERVAL_SECONDS=59,
        )


def test_mail_worker_poll_interval_longer_value_allowed_in_production() -> None:
    """production 調長（降低輪詢頻率）不影響速率上限語意，照收。"""
    s = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://t:t@localhost/t",
        JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
        DEBUG=False,
        FRONTEND_BASE_URL="https://edms.example.com",
        TRUSTED_PROXY_COUNT=0,
        DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,
        ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
        MAIL_WORKER_POLL_INTERVAL_SECONDS=120,
    )
    assert s.MAIL_WORKER_POLL_INTERVAL_SECONDS == 120


# --- MIGRATION_DATABASE_URL（#22：migration 與 app 執行期分用 DB 角色）---


def _settings_with_db_urls(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://app:p@localhost/edms",
        "JWT_SECRET_KEY": "unit-test-secret-key-at-least-32-bytes-long",
        "DEBUG": True,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


def test_migration_url_falls_back_to_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定時退回 DATABASE_URL——合併後既有部署不改任何設定也能照常跑 migration。"""
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    assert _settings_with_db_urls().migration_database_url == "postgresql+asyncpg://app:p@localhost/edms"


def test_migration_url_prefers_dedicated_setting() -> None:
    """有設定時 migration 改用它（資料表 owner），app 執行期仍用 DATABASE_URL（最小權限角色）。"""
    s = _settings_with_db_urls(MIGRATION_DATABASE_URL="postgresql+asyncpg://owner:p@localhost/edms")
    assert s.migration_database_url == "postgresql+asyncpg://owner:p@localhost/edms"
    assert s.DATABASE_URL == "postgresql+asyncpg://app:p@localhost/edms"


@pytest.mark.parametrize("blank", ["", "   "])
def test_migration_url_blank_treated_as_unset(blank: str) -> None:
    """空值（`.env` 留 `MIGRATION_DATABASE_URL=` 範本行）視同未設定，不可拿空字串去連線。"""
    assert _settings_with_db_urls(MIGRATION_DATABASE_URL=blank).migration_database_url == (
        "postgresql+asyncpg://app:p@localhost/edms"
    )


def test_alembic_env_uses_migration_url() -> None:
    """`alembic/env.py` 的線上 / 離線兩條路徑都必須取 `migration_database_url`，不可直接讀 DATABASE_URL。

    直接讀 DATABASE_URL 的話，切到最小權限角色後 migration 會以 app 角色執行而在 DDL 失敗。
    以 AST 檢查屬性存取，不靠字串比對（註解裡出現同一段字不算數）。
    """
    env = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
    attrs = [
        n.attr
        for n in ast.walk(ast.parse(env.read_text(encoding="utf-8")))
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "settings"
    ]
    assert attrs.count("migration_database_url") == 2
    assert "DATABASE_URL" not in attrs


@pytest.mark.parametrize(
    "migration_url",
    [
        "postgresql+asyncpg://owner:p@otherhost/edms",
        "postgresql+asyncpg://owner:p@localhost:5433/edms",
        "postgresql+asyncpg://owner:p@localhost/edms_dev",
        "postgresql+asyncpg://owner:p@localhost/edms?host=/run/postgresql",
    ],
    ids=["host", "port", "database", "query-host"],
)
def test_migration_url_must_target_same_database(migration_url: str) -> None:
    """只能換帳號、不能換庫：指向別的 host / port / 庫時啟動即擋，訊息不回顯連線字串。"""
    with pytest.raises(RuntimeError) as exc_info:
        _build_settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://app:p@localhost/edms",
            JWT_SECRET_KEY="unit-test-secret-key-at-least-32-bytes-long",
            DEBUG=True,
            MIGRATION_DATABASE_URL=migration_url,
        )
    message = str(exc_info.value)
    assert "MIGRATION_DATABASE_URL" in message
    assert "owner:p" not in message


def test_migration_url_same_database_explicit_default_port_accepted() -> None:
    """同一個庫、只差在有沒有寫出預設埠 5432 → 視為相同。"""
    s = _settings_with_db_urls(MIGRATION_DATABASE_URL="postgresql+asyncpg://owner:p@LOCALHOST:5432/edms")
    assert s.migration_database_url.startswith("postgresql+asyncpg://owner:p@")


def test_pytest_ignores_migration_url_from_dotenv() -> None:
    """tests/conftest.py 把 MIGRATION_DATABASE_URL 清空：backend/.env 設了指向 dev 庫的值也不影響測試。

    少了這一步，那個值會被 Settings 從 .env 補讀，與測試庫不同庫而在 import 時被 validator 擋下，
    整批測試在 collection 階段失敗（CI 沒有 .env，看不到）。
    """
    from app.core.config import settings

    assert os.environ["MIGRATION_DATABASE_URL"] == ""
    assert settings.migration_database_url == settings.DATABASE_URL


# ─────────────────────────────────────────────────────────────────────────────
# DB_ECHO 與 DEBUG 解耦（#197 AC 5）
# ─────────────────────────────────────────────────────────────────────────────


def _settings(**overrides: object) -> Settings:
    """建立 hermetic 的 Settings（只給必填 + 指定覆寫）。"""
    base: dict[str, object] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://t:t@localhost/t",
        "JWT_SECRET_KEY": "unit-test-secret-key-at-least-32-bytes-long",
        "DEBUG": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_db_echo_預設關閉() -> None:
    """SQLAlchemy 的 echo 會把**每次查詢的綁定參數**原樣印進 log，預設必須是關的。"""
    assert _settings().DB_ECHO is False


def test_開啟_debug_不會連帶打開_db_echo() -> None:
    """🔴 本條是 #197 AC 5 的核心：echo 與 DEBUG **解耦**。

    解耦之前 `db.py` 寫的是 `echo=settings.DEBUG`，於是 DEBUG 這一個開關同時控制
    三道 production 護欄（`config.py` 的 FRONTEND_BASE_URL / TRUSTED_PROXY_COUNT /
    儲存根）**與**全量 SQL 參數記錄。

    而 `config.py` 自己記錄過 DEBUG 被當逃生門用的情境（「現場只能以 DEBUG=true 繞過」）
    ——真的有人在正式環境開 DEBUG 救火，SQLAlchemy 就開始把病人／員工個資印進 log，
    而 `core/log_redaction` **涵蓋不到 `sqlalchemy.engine` 這條 logger**（該檔「未涵蓋的
    既有暴露面」有明文）。
    """
    assert _settings(DEBUG=True).DB_ECHO is False, "DEBUG 不得連帶打開 SQL 參數記錄"


def test_db_echo_可獨立開啟() -> None:
    """正向錨點：解耦不是把功能拿掉——要看 SQL 時設一個鍵就有，且**不必開 DEBUG**。

    沒有這條的話，上面兩條用「永遠回 False」也會通過。
    刻意用 production（`DEBUG=False`）情境，才證得了「不靠 DEBUG 也開得起來」。
    """
    s = _settings(
        DEBUG=False,
        DB_ECHO=True,
        FRONTEND_BASE_URL="https://edms.example.com",  # 以下三項為 DEBUG=false 的既有護欄
        TRUSTED_PROXY_COUNT=0,
        DM_FILE_STORAGE_ROOT=_ABS_DM_ROOT,
        ET_VIDEO_STORAGE_ROOT=_ABS_ET_ROOT,
    )
    assert s.DB_ECHO is True


def test_engine_的_echo_取自_db_echo_而非_debug() -> None:
    """守門：`db.py` 建 engine 時用的是 `DB_ECHO`。

    ⚠️ 以原始碼比對而非讀 `engine.echo`——module-level 的 `engine` 在 import 時就以當下的
    settings 建好，測試改不了它。要驗的是「下一個人不會把它改回 `settings.DEBUG`」。
    """
    source = (Path(__file__).resolve().parents[2] / "app" / "core" / "db.py").read_text(encoding="utf-8")
    assert "echo=settings.DB_ECHO" in source, "engine 的 echo 應取自 DB_ECHO"
    assert "echo=settings.DEBUG" not in source, "⛔ 不得改回與 DEBUG 綁在一起（#197 AC 5）"


# --- DB_IDLE_IN_TRANSACTION_TIMEOUT_MS 與 MAIL_SEND_TIMEOUT_SEC 的大小關係（#905 A2）---


def test_mail_send_timeout_defaults_to_120() -> None:
    """aiosmtplib 自己的逾時是每個 SMTP 指令 60 秒；整封與它同值會把「慢但能通」的伺服器誤判失敗（code review）。"""
    assert Settings.model_fields["MAIL_SEND_TIMEOUT_SEC"].default == 120


def test_idle_timeout_shorter_than_twice_mail_send_timeout_fails_startup() -> None:
    """發信 worker 寄一封信期間握著交易；閒置逾時比它短的話，寄出成功卻寫不回 SENT，每一輪都重寄同一封
    （security review M1）。只改其中一個 env 就會悄悄抵銷 #905 A2，所以在啟動時擋下。"""
    with pytest.raises(ValueError, match="DB_IDLE_IN_TRANSACTION_TIMEOUT_MS"):
        _settings_with_scan_ttl(MAIL_SEND_TIMEOUT_SEC=200, DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=300_000)


def test_idle_timeout_zero_disables_the_check() -> None:
    """0 = 不限，與寄信時限無關。"""
    assert _settings_with_scan_ttl(MAIL_SEND_TIMEOUT_SEC=600, DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=0)


def test_idle_timeout_defaults_pass_the_check() -> None:
    """正向錨點：預設值本身要能啟動，且邊界（剛好 2 倍）放行。"""
    assert _settings_with_scan_ttl()
    assert _settings_with_scan_ttl(MAIL_SEND_TIMEOUT_SEC=150, DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=300_000)
