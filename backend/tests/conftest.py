"""測試共用設定。

在 import app.core.config.settings 之前設定 fallback 環境變數，
確保 unit 測試不需要真實 .env 也能載入 Settings。

integration 測試（需要真實 DB 連線）的 DB fixtures 待「認證 task」引入第一批
model 與 migration 時，於 tests/integration/conftest.py 建立。
"""

import os

# 若環境已有此變數（CI 注入或本機 .env），setdefault 不會覆蓋。
# unit 測試只需 settings 能載入；此 URL 不會實際連線。
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_edms",
)
# JWT_SECRET_KEY 為必填設定；unit 測試以固定測試值滿足載入，不用於任何真實簽章。
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production")
