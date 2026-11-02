#!/usr/bin/env bash
# ============================================================
# EDMS Local CI — 在本地模擬 GitHub CI 的所有檢查
#
# 用法：
#   ./scripts/local-ci.sh             # 跑全部（不含 E2E）
#   ./scripts/local-ci.sh quick       # 只跑 lint / format / type-check（最快）
#   ./scripts/local-ci.sh backend     # 只跑後端
#   ./scripts/local-ci.sh frontend    # 只跑前端
#   ./scripts/local-ci.sh all --e2e   # 跑全部 + E2E（Playwright，見 e2e/README.md）
#   ./scripts/local-ci.sh --e2e       # 同上（未指定模式時為 all）
#
# E2E 預設不跑：慢、且需額外前置（PostgreSQL 上的 e2e_ 專用庫、mailpit、chromium），
# 不該拖慢日常開發（#57）。結果彙總會明確標示本次「含 / 不含 E2E」。
#
# 需要整合測試時，請確保 PostgreSQL 正在運行且 backend/.env.test 已設定。
# 前端尚未建立時（frontend/ 不存在）會自動 skip 前端檢查，不報錯。
# 檢查項與 .github/workflows/ci.yml 對齊——本機綠燈 ≒ 未來 CI 綠燈。
# ============================================================

set -uo pipefail
# 不使用 set -e：run_step 自行管理成功/失敗狀態，允許某步失敗後繼續執行其他檢查

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE=""
RUN_E2E=false

usage() {
    echo "用法: $0 [all|quick|backend|frontend] [--e2e]"
}

# 參數：至多一個模式 + 選填 --e2e（順序不拘）
for arg in "$@"; do
    case "$arg" in
        --e2e) RUN_E2E=true ;;
        all|quick|backend|frontend)
            if [[ -n "$MODE" ]]; then usage; exit 1; fi
            MODE="$arg"
            ;;
        *) usage; exit 1 ;;
    esac
done
MODE="${MODE:-all}"

# quick 的定位是「最快的靜態檢查」，與 E2E 相牴觸，直接拒絕而非默默忽略 --e2e
if [[ "$MODE" == "quick" && "$RUN_E2E" == "true" ]]; then
    echo "quick 模式不跑測試，不可與 --e2e 併用"
    exit 1
fi

if [[ "$RUN_E2E" == "true" ]]; then
    E2E_LABEL="含 E2E"
else
    E2E_LABEL="不含 E2E"
fi

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

# ──────────────────────────────────────────────────────────
# 併行測試偵測（#635）
# ──────────────────────────────────────────────────────────
# 這台機器由多個 session 共用，而後端階段是 `pytest -n auto`（12 核 → 12 worker）。
# 只要有人照專案文件跑標準的本機 CI，另一個 session 的前端 vitest 就會假紅——那是
# 工具預設與共用機器的**結構衝突**，不是誰的疏忽，所以會反覆發生。
#
# ⛔ 刻意「警告」而不是「擋下」：腳本分不出**孤兒 worker**（沒有人在跑、worker 卻還在）
#    與活人。直接擋會把「等到天荒地老」變成預設行為，也會讓背景／非互動執行整組失敗。
#    決定權留給看得到 cwd 的人。環境變數 EDMS_CI_BLOCK_ON_BUSY=1 可升級成擋下。
#
# 🔴 指紋清單的**唯一事實來源**在 `scripts/detect-test-procs.ps1` 的 $pattern。
#    新增 runner 改那一處；`.claude/rules/sti-testing.md` 的步驟 0 指向它，不另抄一份。
CONCURRENT_REPORT=""

detect_concurrent_tests() {
    local script="${ROOT_DIR}/scripts/detect-test-procs.ps1"
    # fail-open：偵測器自身的任何問題都只印一行說明，CI 不因它而失敗。
    [[ -f "$script" ]] || { echo -e "${YELLOW}⚠ 找不到 detect-test-procs.ps1，略過併行測試偵測${NC}"; return 0; }
    command -v powershell >/dev/null 2>&1 || { echo -e "${YELLOW}⚠ 無 powershell，略過併行測試偵測${NC}"; return 0; }

    local raw
    if ! raw="$(powershell -NoProfile -ExecutionPolicy Bypass -File "$script" 2>/dev/null | tr -d '\r')"; then
        echo -e "${YELLOW}⚠ 併行測試偵測失敗，略過（CI 不因此失敗）${NC}"
        return 0
    fi
    [[ -n "$raw" ]] || return 0   # 機器乾淨：不增加任何輸出雜訊

    local pid name cpu wt cmd cores="?" lines=""
    while IFS=$'\t' read -r pid name cpu wt cmd; do
        [[ -z "$pid" ]] && continue
        if [[ "$pid" == "#CORES" ]]; then cores="$name"; continue; fi
        lines+="    PID ${pid}  ${name}  cpu=${cpu}%  worktree=${wt}"$'\n'
        # 🔴 命令列是 Windows 路徑，含 `\E`、`\b`、`\t` 等序列。本報告最後由 `echo -e`
        # 輸出（要處理顏色碼），而 `echo -e` 會把它們當跳脫字元吃掉：實測
        # `TBMS_git\EDMS\backend` 被印成 `TBMS_gitDMSackend`（\E→ESC、\b→退格）。
        # 先把反斜線加倍，`echo -e` 解析後正好還原成一個。
        lines+="        ${cmd//\\/\\\\}"$'\n'
    done <<< "$raw"

    CONCURRENT_REPORT="$(cat <<EOF
${YELLOW}⚠ 偵測到其他測試行程正在跑（本機 ${cores} 核，與本輪互搶 CPU）${NC}
${lines}    兩種情況，先分辨是哪一種：
      • ${YELLOW}有主人${NC}：某個 session 正在跑 → 等它跑完，或請對方降併發度
      • ${YELLOW}孤兒${NC}：沒有人在跑、worker 卻還在（中止背景測試不會收掉 xdist worker）
        → 問過一輪沒人認領就直接收掉，${RED}「等對方跑完」對孤兒是錯的建議${NC}
    ⚠ cpu=0% ${YELLOW}不代表沒影響${NC}：那是取樣瞬間值，且 venv 的 launcher shim 恆為 0%
      （同一個 worker 會出現兩列，有 CPU 的那層才是真的在跑）
    判讀細節見 .claude/rules/sti-testing.md〈前端「假紅」判定〉步驟 0
EOF
)"
    echo ""
    echo -e "$CONCURRENT_REPORT"

    if [[ "${EDMS_CI_BLOCK_ON_BUSY:-}" == "1" ]]; then
        echo -e "${RED}EDMS_CI_BLOCK_ON_BUSY=1 已設定，中止本輪${NC}"
        exit 2
    fi
}

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

# 🔴 不可寫成 $(uv run alembic heads | wc -l)：崩潰時 traceback 走 stderr、stdout 為空，
# wc -l 得 0 → 被當成「正常」（#598）。須先檢查指令本身的 exit code。
check_alembic_heads() {
    local heads count
    if ! heads=$(uv run alembic heads 2>&1); then
        echo "alembic heads 執行失敗（非 head 數問題）："
        echo "$heads"
        return 1
    fi
    # 數 "(head)" 標記而非行數；grep 零命中時 exit 1，故以 || true 兜底。
    # 0 個也視為失敗：本 repo 已有 migration，數到 0 代表輸出格式不如預期，寧紅勿綠。
    count=$(printf '%s\n' "$heads" | grep -c '(head)' || true)
    # :-0 兜底：萬一 grep 自身出錯而無輸出，[ "" -ne 1 ] 會判為 false 而放行
    if [ "${count:-0}" -ne 1 ]; then
        echo "發現 ${count} 個 Alembic head，請先執行 /sti-alembic-check 合併"
        echo "$heads"
        return 1
    fi
    echo "✅ Alembic head 正常（單一 head）：${heads}"
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

    # 🔴 讓底下每個 `uv run ...` 拒絕改寫 uv.lock（#541）。
    # 沒有這行的話：下方「uv.lock 一致性」紅掉後本腳本仍會續跑，而 `uv run ruff ...` 會
    # **重新解析整棵相依樹**並改寫工作區的 uv.lock——不只是補上你漏掉的那一個，而是可能把
    # 任意傳遞相依拉到當下 PyPI 最新版（含幾小時前才發布、沒人看過的）。
    # 接著彙總表洗版、`git status` 多出的 uv.lock 很容易連同功能變更一起 `git add -A`，
    # 變成一次**未經 review 的相依樹更新**偽裝成「順手補上的 lock」。
    # ⚠️ 本專案才剛為 github-actions 設了 7 天供應鏈冷卻（`.github/dependabot.yml`），
    # 這條路徑會整個繞過那個考量。
    # ⛔ 不要改用 `UV_FROZEN=1`：那是「完全不檢查、直接照 lock 裝」，會抵銷下面這道檢查。
    export UV_LOCKED=1

    # 0. uv.lock 與 pyproject.toml 一致性（#541）
    # 本機原本完全沒有這道檢查，而遠端 CI 的 `uv sync --dev`（未帶 --locked）會在 lock
    # 過期時自行重解並改寫——於是「改了 pyproject 忘了跑 uv lock」兩邊都不會出聲，
    # 卻會讓正式映像（`uv sync --frozen`）照過期的 lock 裝、靜默少裝套件。
    # 與 ci.yml 的「檢查 uv.lock 與 pyproject.toml 一致」對齊，避免本機綠、遠端紅。
    #
    # ⚠️ 這一步紅掉後本腳本仍會往下跑（`run_step` 的設計），但因上方 `UV_LOCKED=1`，
    # 後續每個 `uv run` 都會明確報錯而非偷偷修好——你會看到一整排紅，那是正確的。
    # 修法：`cd backend && uv lock`，然後**先看 `git diff uv.lock` 確認只有你預期的那幾個
    # 套件變動**再 commit。⛔ 不要略過那一眼：`uv lock` 會重解整棵樹，差異未必只有你加的那個。
    run_step "Backend: uv.lock 一致性" uv lock --check

    # 1. Ruff lint
    run_step "Backend: ruff lint" uv run ruff check .

    # 2. Ruff format check
    run_step "Backend: ruff format" uv run ruff format --check .

    # 3. Alembic heads 檢查（確保只有單一 migration head）
    # 註：alembic heads 會載入全部 migration 檔，其中有一支在 module 層 import settings，
    #     需要 backend/.env 提供 DATABASE_URL / JWT_SECRET_KEY 等設定，但不會實際連線 DB；
    #     若缺 .env 會直接報錯，故先檢查 .env 是否存在。
    # ⚠️ 本機綠燈不代表 merge 後單頭：多頭是「分支 + main」合起來才有的狀態，
    #     只有 CI（測 merge commit）看得到。本機這道只攔得下自己分支內的多頭。
    if [[ ! -f .env ]]; then
        echo -e "${YELLOW}  ⚠ 找不到 backend/.env，跳過 alembic heads 檢查${NC}"
        echo -e "${YELLOW}    請執行：cp .env.example .env 並設定必要欄位${NC}"
        skip_step "Backend: alembic heads"
    else
        # 判定邏輯與 ci.yml「檢查 Alembic heads」對齊，避免本地通過但 CI 失敗
        run_step "Backend: alembic heads" check_alembic_heads
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
# E2E（Playwright，僅 --e2e 時執行）
#
# Playwright 會自行起 E2E 專用的後端（:8101）與前端（:4174），不碰 dev server 與 dev DB。
# 前置（PostgreSQL 上的 e2e_ 專用庫、mailpit、chromium）見 e2e/README.md。
# ──────────────────────────────────────────────────────────
run_e2e() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         E2E (Playwright)             ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"

    command -v pnpm &>/dev/null || { echo -e "${RED}ERROR: pnpm not found${NC}"; FAILED+=("E2E (pnpm missing)"); return; }

    # 明確要求跑 E2E 卻缺依賴 → 記為失敗而非 skip：使用者下了 --e2e，「綠燈但其實沒跑」比紅燈更糟
    if [[ ! -d "$ROOT_DIR/e2e/node_modules" ]]; then
        echo -e "${RED}  ✘ 尚未安裝 E2E 依賴：cd e2e && pnpm install && pnpm install:browser${NC}"
        FAILED+=("E2E: Playwright (依賴未安裝)")
        return
    fi
    if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
        echo -e "${RED}  ✘ E2E 需建置前端，請先：cd frontend && pnpm install${NC}"
        FAILED+=("E2E: Playwright (前端依賴未安裝)")
        return
    fi

    cd "$ROOT_DIR/e2e"
    run_step "E2E: type-check" pnpm type-check
    run_step "E2E: Playwright" pnpm test
    cd "$ROOT_DIR"
}

# ──────────────────────────────────────────────────────────
# 執行
# ──────────────────────────────────────────────────────────

echo -e "${BLUE}EDMS Local CI${NC} — mode: ${YELLOW}${MODE}${NC}（${E2E_LABEL}）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

detect_concurrent_tests

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

if [[ "$RUN_E2E" == "true" ]]; then
    run_e2e
fi

# ──────────────────────────────────────────────────────────
# 結果彙總
# ──────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}結果彙總${NC}（${E2E_LABEL}）"
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
    # 🔴 明文列出失敗項，不要只靠 ✔ / ✘ 符號（#635）。
    # 實際事故（2026-10-14）：有人 grep `✖` 判讀自己的結果，而本腳本印的是 `✘`
    # ——U+2716 vs U+2718，不同碼位。於是只撈到 ✔ 行，把「後端全綠」回報出去，
    # 而實際有兩道紅。⚠️ 符號比對漏掉時，錯的方向剛好是**看起來全綠**。
    # 明文摘要讓「有沒有失敗」不必由讀者從缺漏去推論——缺漏是最容易被合理化掉的訊號。
    local_ci_failed_list="$(printf '%s, ' "${FAILED[@]}")"
    echo "FAILED: ${local_ci_failed_list%, }"
    echo ""
    echo -e "${RED}CI 失敗（${E2E_LABEL}）：${#FAILED[@]} 個檢查未通過${NC}"
    # 併行測試的警告在開頭印過一次，這裡**再印一次**：前端真的紅的時候，
    # 警告就在紅字旁邊，正是需要它的那一刻（開頭那次早被 10 分鐘的 log 埋掉了）。
    if [[ -n "$CONCURRENT_REPORT" ]]; then
        echo ""
        echo -e "$CONCURRENT_REPORT"
    fi
    exit 1
else
    echo ""
    echo -e "${GREEN}CI 通過（${E2E_LABEL}）：${#PASSED[@]} 個檢查成功，${#SKIPPED[@]} 個跳過${NC}"
    if [[ "$RUN_E2E" != "true" ]]; then
        echo -e "${YELLOW}  未跑 E2E；需要時加 --e2e（或 pnpm ci:local:e2e）${NC}"
    fi
    exit 0
fi
