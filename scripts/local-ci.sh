#!/usr/bin/env bash
# ============================================================
# EDMS Local CI — 在本地模擬 GitHub CI 的所有檢查
#
# 用法：
#   ./scripts/local-ci.sh          # 跑全部（不含 E2E）
#   ./scripts/local-ci.sh quick    # 只跑 lint / format / type-check（最快）
#   ./scripts/local-ci.sh backend  # 只跑後端
#   ./scripts/local-ci.sh frontend # 只跑前端
#
# 需要整合測試時，請確保 PostgreSQL 正在運行且 backend/.env.test 已設定。
# 前端尚未建立時（frontend/ 不存在）會自動 skip 前端檢查，不報錯。
# 檢查項與 .github/workflows/ci.yml 對齊——本機綠燈 ≒ 未來 CI 綠燈。
# ============================================================

set -uo pipefail
# 不使用 set -e：run_step 自行管理成功/失敗狀態，允許某步失敗後繼續執行其他檢查

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-all}"

# 白名單驗證：緊接 MODE 賦值之後，防止重構時順序被打亂
case "$MODE" in
    all|quick|backend|frontend) ;;
    *)
        echo "用法: $0 [all|quick|backend|frontend]"
        exit 1
        ;;
esac

# 前置檢查：確認必要工具已安裝（前端工具在有 frontend/ 時才要求）
for cmd in uv git; do
    command -v "$cmd" &>/dev/null || { echo "ERROR: $cmd not found, please install it first."; exit 1; }
done

# 顏色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASSED=()
FAILED=()
SKIPPED=()

run_step() {
    local name="$1"
    shift
    echo ""
    echo -e "${BLUE}━━━ ${name} ━━━${NC}"
    if "$@"; then
        PASSED+=("$name")
        echo -e "${GREEN}  ✔ ${name}${NC}"
    else
        FAILED+=("$name")
        echo -e "${RED}  ✘ ${name}${NC}"
    fi
}

skip_step() {
    local name="$1"
    SKIPPED+=("$name")
    echo -e "${YELLOW}  ⊘ ${name} (skipped)${NC}"
}

# ──────────────────────────────────────────────────────────
# 後端檢查
# ──────────────────────────────────────────────────────────
run_backend() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         Backend Checks               ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"

    cd "$ROOT_DIR/backend"

    # 1. Ruff lint
    run_step "Backend: ruff lint" uv run ruff check .

    # 2. Ruff format check
    run_step "Backend: ruff format" uv run ruff format --check .

    # 3. Alembic heads 檢查（確保只有單一 migration head）
    # 註：alembic 會載入 env.py，需要 backend/.env 提供 DATABASE_URL / JWT_SECRET_KEY 等設定，
    #     但不會實際連線 DB；若缺 .env 會直接報錯，故先檢查 .env 是否存在。
    #     versions/ 為空時 alembic heads 無輸出（0 head），亦視為正常。
    if [[ ! -f .env ]]; then
        echo -e "${YELLOW}  ⚠ 找不到 backend/.env，跳過 alembic heads 檢查${NC}"
        echo -e "${YELLOW}    請執行：cp .env.example .env 並設定必要欄位${NC}"
        skip_step "Backend: alembic heads"
    else
        # 使用 wc -l 與 CI workflow 對齊（ci.yml），避免本地通過但 CI 失敗
        run_step "Backend: alembic heads" bash -c '
            HEAD_COUNT=$(uv run alembic heads | wc -l)
            if [ "$HEAD_COUNT" -gt 1 ]; then
                echo "發現 ${HEAD_COUNT} 個 Alembic head，請先執行 /sti-alembic-check 合併"
                uv run alembic heads
                exit 1
            fi
            echo "✅ Alembic head 正常（單一 head 或尚無 migration）"
        '
    fi

    # 4. Unit tests
    run_step "Backend: unit tests" uv run pytest -m unit -v

    # 5. Integration tests（需要 test DB；migration 由 pytest fixture apply_migrations 自動套用）
    if [[ "$MODE" == "quick" ]]; then
        skip_step "Backend: integration tests"
        skip_step "Backend: diff-cover"
    elif [[ ! -f .env.test ]]; then
        echo -e "${YELLOW}  ⚠ 找不到 backend/.env.test，跳過整合測試${NC}"
        echo -e "${YELLOW}    第一張 migration 落地時建立（cp .env.example .env.test 並改指向 test_edms）${NC}"
        skip_step "Backend: integration tests"
        skip_step "Backend: diff-cover"
    else
        # 連線檢查：只讀 .env.test（整合測試僅允許連測試 DB，避免誤動 dev DB）
        DB_CHECK_LOG="/tmp/edms-db-check.log"
        if uv run python -c "
import asyncio
from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def check():
    vals = dotenv_values('.env.test')
    url = vals.get('DATABASE_URL', '')
    if not url:
        raise Exception('.env.test 未設定 DATABASE_URL')
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
    await engine.dispose()
asyncio.run(check())
" 2>"$DB_CHECK_LOG"; then
            # 全部測試 + 覆蓋率（apply_migrations fixture 會自動 upgrade/downgrade test DB schema）
            # -n auto：pytest-xdist 依核心數並行跑（每個 worker 自帶獨立 DB，見 tests/conftest.py）
            run_step "Backend: all tests + coverage" \
                uv run pytest -v -n auto --cov --cov-report=xml --cov-report=term-missing

            # diff-cover（對比 origin/main），先更新參考點，確保比較基準跟 CI 一致
            git fetch origin main &>/dev/null
            if git rev-parse --verify origin/main &>/dev/null; then
                run_step "Backend: diff-cover (80%)" \
                    uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
            else
                skip_step "Backend: diff-cover (no origin/main)"
            fi
        else
            echo -e "${YELLOW}  ⚠ 無法連線測試 PostgreSQL，跳過整合測試${NC}"
            echo -e "${YELLOW}    請確認 backend/.env.test 的 DATABASE_URL 設定正確${NC}"
            echo -e "${YELLOW}    詳細錯誤請查看：${DB_CHECK_LOG}${NC}"
            skip_step "Backend: integration tests"
            skip_step "Backend: diff-cover"
        fi
    fi

    cd "$ROOT_DIR"
}

# ──────────────────────────────────────────────────────────
# 前端檢查（frontend/ 尚未建立時整段 skip）
# ──────────────────────────────────────────────────────────
run_frontend() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         Frontend Checks              ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"

    # 前端尚未建立（無 frontend/package.json）→ 整段 skip，不報錯
    if [[ ! -f "$ROOT_DIR/frontend/package.json" ]]; then
        echo -e "${YELLOW}  ⚠ 尚無 frontend/（前端骨架未建立），跳過前端檢查${NC}"
        skip_step "Frontend: ESLint"
        skip_step "Frontend: type-check"
        skip_step "Frontend: tests"
        return
    fi

    command -v pnpm &>/dev/null || { echo -e "${RED}ERROR: pnpm not found${NC}"; skip_step "Frontend (pnpm missing)"; return; }

    cd "$ROOT_DIR/frontend"

    run_step "Frontend: ESLint" pnpm lint
    run_step "Frontend: type-check" pnpm type-check

    if [[ "$MODE" == "quick" ]]; then
        skip_step "Frontend: tests"
    else
        run_step "Frontend: tests" pnpm test
    fi

    cd "$ROOT_DIR"
}

# ──────────────────────────────────────────────────────────
# 執行
# ──────────────────────────────────────────────────────────

echo -e "${BLUE}EDMS Local CI${NC} — mode: ${YELLOW}${MODE}${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

case "$MODE" in
    all|quick)
        run_backend
        run_frontend
        ;;
    backend)
        run_backend
        ;;
    frontend)
        run_frontend
        ;;
esac

# ──────────────────────────────────────────────────────────
# 結果彙總
# ──────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}結果彙總${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ ${#PASSED[@]} -gt 0 ]]; then
    for step in "${PASSED[@]}"; do
        echo -e "  ${GREEN}✔${NC} $step"
    done
fi

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    for step in "${SKIPPED[@]}"; do
        echo -e "  ${YELLOW}⊘${NC} $step"
    done
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
    for step in "${FAILED[@]}"; do
        echo -e "  ${RED}✘${NC} $step"
    done
    echo ""
    echo -e "${RED}CI 失敗：${#FAILED[@]} 個檢查未通過${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}CI 通過：${#PASSED[@]} 個檢查成功，${#SKIPPED[@]} 個跳過${NC}"
    exit 0
fi
