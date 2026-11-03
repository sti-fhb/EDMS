"""測試共用設定。

在 import app.core.config.settings 之前設定 fallback 環境變數，
確保 unit 測試不需要真實 .env / .env.test 也能載入 Settings。

integration 測試（需要真實 DB 連線）的 DB fixtures（apply_migrations、
test_engine、db）定義在 tests/integration/conftest.py，unit 測試不受影響。
"""

import os

from tests._xdist_db import worker_database_url

# 若環境已有此變數（pytest-dotenv 載入 .env.test，或 CI 直接注入），setdefault 不覆蓋。
# unit 測試只需 settings 能載入；此 URL 不會實際連線。
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_edms",
)
# JWT_SECRET_KEY 為必填設定；unit 測試以固定測試值滿足載入，不用於任何真實簽章。
# 長度須達 app.core.config 對 HS256 要求的 32 bytes，否則 settings 載入失敗；門檻調整時須跟著改。
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production-32b+")
# DEBUG：測試 / CI 屬非 production。設 true 以免 FRONTEND_BASE_URL 的 production 護欄
# （見 app.core.config._validate_frontend_base_url）在 CI（無 .env、FRONTEND_BASE_URL 落回
# localhost 預設）擋下 settings 載入，導致全數測試 collection error。
os.environ.setdefault("DEBUG", "true")
# MIGRATION_DATABASE_URL 一律清空（#22），刻意不用 setdefault：Settings 會從 backend/.env 補讀它，
# 開發者在 .env 設了指向 dev 庫的值時，與測試庫不同庫 → 「只能換帳號、不能換庫」的 validator 在 import
# 時就擋下，整批測試在 collection 階段全紅。環境變數優先於 .env，空字串視同未設定（退回 DATABASE_URL）。
# integration 的 alembic 子程序另在 tests/integration/conftest.py 顯式帶入測試庫。
os.environ["MIGRATION_DATABASE_URL"] = ""
# 上傳前的磁碟剩餘空間檢查（#905 A1）預設 10 GB；CI runner 不保證有這麼多，上傳的 integration 測試會被
# 擋成 507。設 0 關閉，檢查本身由 tests/unit/test_core_upload_disk_guard.py 以替身與真實磁碟驗證。
os.environ.setdefault("UPLOAD_MIN_FREE_DISK_MB", "0")

# pytest-xdist 並行：每個 worker 改用自己的資料庫，避免多行程互相 DROP SCHEMA。
# 必須在 app.core.config.settings 第一次 import 之前改寫（否則 settings 會 cache 舊庫名）。
# 非並行時 PYTEST_XDIST_WORKER 未設定，URL 原樣不變；實際建庫 / 刪庫在
# tests/integration/conftest.py 的 apply_migrations（僅 integration 載入，unit 不受影響）。
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker:
    os.environ["DATABASE_URL"] = worker_database_url(os.environ["DATABASE_URL"], _xdist_worker)
