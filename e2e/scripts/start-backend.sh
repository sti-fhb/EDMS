#!/usr/bin/env bash
# ============================================================
# E2E 專用後端啟動（由 e2e/playwright.config.ts 的 webServer 呼叫）
#
#   1. 擋下非 `e2e_` 開頭的 DB 名——E2E 會跑 migration、塞測試帳號，
#      絕不能落在共用 dev DB（edms）或 integration test DB（test_edms*）
#   2. alembic upgrade head（CI 為全新空庫；本機為持續累積的 E2E 專用庫）
#   3. 以 uvicorn 起後端（單 worker、不開 reload）
#
# 所需環境變數由 playwright.config.ts 注入，不要直接執行本檔。
# ============================================================
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL 未設定（應由 playwright.config.ts 注入）}"
: "${E2E_API_PORT:?E2E_API_PORT 未設定（應由 playwright.config.ts 注入）}"

cd "$(dirname "$0")/../../backend"

# 🔴 護欄必須與「實際連線」用同一個解析器：alembic / uvicorn 走 SQLAlchemy make_url → asyncpg。
# 改用 urllib.parse 會被繞過（實測）：
#   - `.../e2e_x?database=edms`      → asyncpg dialect 以 query 的 database 覆寫 path，實際連 edms
#   - `user:pw/e2e_x?@host/edms`     → SQLAlchemy 允許密碼含 / 與 ?，urlparse 卻把它當 path
# 故一律以 make_url 取 database，並拒絕任何 query 參數（E2E 用不到）。
# 經 uv 執行而非系統 python3：Windows Git Bash 的 python3 常是 Store stub 或不存在。
# 失敗訊息刻意不印取到的值——URL 格式異常時那段可能是密碼。
if ! uv run --locked python -I -c '
import re, sys
from sqlalchemy.engine import make_url
try:
    u = make_url(sys.argv[1])
except Exception:
    # make_url 的例外訊息會原樣帶出整串 URL（含密碼），不可外拋
    sys.exit("E2E 的 DATABASE_URL 格式無法解析")
if u.query:
    sys.exit("E2E 的 DATABASE_URL 不可帶 query 參數（可能覆寫實際連線的 DB 名）")
if not re.fullmatch(r"e2e_[a-z0-9_]+", u.database or ""):
    sys.exit("E2E 的 DB 名必須以 e2e_ 開頭（僅限 [a-z0-9_]）")
print(f"✓ E2E DB：{u.database}")
' "$DATABASE_URL"; then
    echo "❌ E2E 會跑 migration 並建立測試帳號，不可指向 dev DB 或 integration test DB。" >&2
    echo "   請設定 E2E_DATABASE_URL，例如 .../e2e_edms（見 e2e/README.md）。" >&2
    exit 1
fi

echo "▶ E2E 後端：alembic upgrade head"
uv run --locked alembic upgrade head

echo "▶ E2E 後端：uvicorn 127.0.0.1:${E2E_API_PORT}"
exec uv run --locked uvicorn main:app --host 127.0.0.1 --port "$E2E_API_PORT" --workers 1 --no-proxy-headers --no-access-log
