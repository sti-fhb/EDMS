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
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production")

# pytest-xdist 並行：每個 worker 改用自己的資料庫，避免多行程互相 DROP SCHEMA。
# 必須在 app.core.config.settings 第一次 import 之前改寫（否則 settings 會 cache 舊庫名）。
# 非並行時 PYTEST_XDIST_WORKER 未設定，URL 原樣不變；實際建庫 / 刪庫在
# tests/integration/conftest.py 的 apply_migrations（僅 integration 載入，unit 不受影響）。
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker:
    os.environ["DATABASE_URL"] = worker_database_url(os.environ["DATABASE_URL"], _xdist_worker)
