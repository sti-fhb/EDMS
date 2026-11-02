# EDMS E2E 測試（Playwright）

真瀏覽器 → 真後端 → 真 DB 的端到端測試（#57）。首批只蓋 3 條 critical path：

| 測試 | 流程 |
|------|------|
| `tests/login.spec.ts` | 登入 → 由側欄進入模組入口頁（教育訓練 › 我的課程） |
| `tests/register.spec.ts` | 自助註冊 → 信箱驗證（設定密碼）→ 登入 |
| `tests/forgot-password.spec.ts` | 忘記密碼 → 信中連結重設 → 以新密碼登入 |

判讀失敗、flaky 處理原則見 `.claude/agents/e2e-runner.md`。

## 架構

```
Playwright ──► 前端 vite preview :4174 ──/api──► E2E 後端 uvicorn :8101 ──► PostgreSQL（e2e_ 專用庫）
     │                                                   └── SMTP ──► mailpit :1025
     └──────────── 取驗證 / 重設連結 ◄──── mailpit API :8025
```

- 後端與前端由 `playwright.config.ts` 的 `webServer` **自動啟動**，port 刻意與 dev（8001 / 5174）錯開，
  手上開著 dev server 也能跑，且不會碰到共用 dev DB（啟動腳本以 SQLAlchemy 解析 `E2E_DATABASE_URL`，
  DB 名非 `e2e_` 開頭或帶 query 參數即拒絕）
- 每條測試自建帳號（隨機尾碼），不依賴示範帳號（`SEED_DEMO_ACCOUNTS=false`）
- 發信 worker 輪距設 1 秒（`MAIL_WORKER_POLL_INTERVAL_SECONDS`），否則每封信最多要等 60 秒

## 本機執行

### 1. 前置（一次性）

```bash
# 依賴與瀏覽器（只裝 chromium）
cd e2e && pnpm install && pnpm install:browser
cd ../frontend && pnpm install
cd ../backend && uv sync
```

**PostgreSQL**：建立一個 **`e2e_` 開頭**的專用庫（啟動腳本會擋下其他名稱，避免誤寫 dev DB 或 integration test DB）：

```sql
CREATE DATABASE e2e_edms;
```

> 多個 worktree 會各自跑 migration：不同分支的 migration 不同時，請每個 worktree 用不同的庫名（如 `e2e_edms_<分支>`），
> 否則會撞到 `Can't locate revision`。

**mailpit**（本機收信服務）擇一：

```bash
# 只綁 127.0.0.1：mailpit 的 Web UI / API 無認證，綁 0.0.0.0 會讓同網段的人讀到信中連結
docker run -d --name edms-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit:v1.32.0
# 或安裝官方執行檔後直接執行：mailpit
```

信件可於 <http://127.0.0.1:8025> 查看。

### 2. 執行

```bash
# 帳密與預設值（edms/edms@127.0.0.1:5432/e2e_edms）不同時才需要設定
export E2E_DATABASE_URL='postgresql+asyncpg://<user>:<password>@127.0.0.1:5432/e2e_edms'

cd e2e
pnpm test                      # 全部
pnpm test tests/login.spec.ts  # 單支
pnpm test:ui                   # 互動模式
pnpm report                    # 開啟上次的 HTML 報表
```

或從 repo 根目錄：`pnpm e2e`；完整本地 CI 加 E2E：`pnpm ci:local:e2e`（`scripts/local-ci.sh --e2e`）。
`pnpm ci:local` **預設不含 E2E**。

### 可覆寫的環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `E2E_DATABASE_URL` | `postgresql+asyncpg://edms:edms@127.0.0.1:5432/e2e_edms` | DB 名須 `e2e_` 開頭 |
| `E2E_API_PORT` | `8101` | E2E 後端 port |
| `E2E_WEB_PORT` | `4174` | E2E 前端（vite preview）port |
| `E2E_MAILPIT_URL` | `http://127.0.0.1:8025` | mailpit HTTP API |
| `E2E_SMTP_HOST` / `E2E_SMTP_PORT` | `127.0.0.1` / `1025` | 後端寄信目標 |

> Playwright **不沿用**已在跑的服務：`E2E_API_PORT` / `E2E_WEB_PORT` 被佔用時會直接報錯。
> 刻意如此——沿用時啟動腳本不會執行，`e2e_` DB 名護欄就失效了。多個 worktree 同時跑時請各自換 port 與 DB 名。

## CI

`.github/workflows/ci.yml` 的 `e2e` job：PR 上後端、前端或 `e2e/` 有變更時觸發；postgres 與 mailpit 以 service container 提供；
`retries: 1`；失敗時上傳 `test-results/`（含 trace）與 HTML 報表為 artifact `playwright-report`。

> ⚠️ trace 含所有網路請求內容（測試帳密、token）。目前全為一次性假資料；日後若 E2E 需要 GitHub secrets
> 或真實外部服務，必須同時停用 trace 上傳（public repo 的 artifact 任何登入者都能下載）。
