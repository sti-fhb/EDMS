import { defineConfig, devices } from "@playwright/test"

import { API_PORT, API_URL, BASE_URL, DATABASE_URL, SMTP_HOST, SMTP_PORT, WEB_PORT } from "./support/env"

const isCI = !!process.env.CI

/**
 * EDMS E2E（#57）：真瀏覽器 → 真後端 → 真 DB，信件由 mailpit 收。
 *
 * 由 webServer 自行起後端（uvicorn）與前端（vite build + preview），本機與 CI 走同一條路徑。
 * Postgres 與 mailpit 為外部前置（CI 由 service container 提供，本機見 e2e/README.md）。
 *
 * ⏱️ 逾時一律明示，不吃框架預設值：真瀏覽器的等待比 jsdom 更不可預測，而前端 vitest 曾因
 * testing-library 預設 1000ms 等待預算長期隨機假紅（#748，見 `.claude/rules/sti-testing.md`
 * 「前端『假紅』判定」）。這裡的數字都是「正常情況遠用不到、真的壞了也不會拖太久」的上限。
 */
export default defineConfig({
  testDir: "./tests",
  // 開跑前確認 mailpit 可連（連不到就一次說清楚）
  globalSetup: "./support/global-setup.ts",
  // 單條測試上限：含等信（≤ 30s）與兩次頁面往返，60s 綽綽有餘
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: isCI,
  // CI 重試 1 次：重試後才綠的測試會在報表標為 flaky，不會被靜默吞掉（判讀原則見 .claude/agents/e2e-runner.md）
  retries: isCI ? 1 : 0,
  // 每條測試自建帳號、互不共用狀態，可並行；上限壓低以免撞登入限流（同 IP 每分鐘 10 次）
  workers: isCI ? 2 : 3,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    // 失敗才留 trace（含重試那一次）；CI 會把 test-results/ 上傳為 artifact
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-TW",
    timezoneId: "Asia/Taipei",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "bash scripts/start-backend.sh",
      url: `${API_URL}/api/version`,
      // 含 alembic upgrade head（全新空庫約數十秒）
      timeout: 180_000,
      // ⛔ 一律不沿用既有服務：沿用時 start-backend.sh 根本不會執行，e2e_ DB 名護欄整段失效——
      // port 上若是別的 worktree 的後端、甚至連著 dev DB 的程序，測試帳號就寫進那個庫。
      // port 被佔時直接報錯（fail-safe），由使用者換 E2E_API_PORT 或關掉佔用者。
      reuseExistingServer: false,
      // DEBUG=true 會讓 SQLAlchemy 把每句 SQL echo 到 stdout（app/core/db.py），量大且無助判讀；
      // 錯誤與 traceback 走 stderr，照收
      stdout: "ignore",
      stderr: "pipe",
      env: {
        E2E_API_PORT: String(API_PORT),
        DATABASE_URL,
        // 假值：僅供 E2E 簽 JWT，長度需 ≥ 32 bytes（HS256 門檻）
        JWT_SECRET_KEY: "e2e-test-secret-key-at-least-32-bytes-long",
        DEBUG: "true",
        TRUSTED_PROXY_COUNT: "0",
        // 每條測試自建帳號，不依賴示範帳號（與 CI 的 integration 測試一致）
        SEED_DEMO_ACCOUNTS: "false",
        // 信中連結要指回 E2E 自己的前端
        FRONTEND_BASE_URL: BASE_URL,
        CORS_ORIGINS: BASE_URL,
        // 寄到 mailpit（不加密、免帳密）；明示清空帳密，免得吃到 backend/.env 的值
        MAIL_SERVER: SMTP_HOST,
        MAIL_PORT: String(SMTP_PORT),
        MAIL_USERNAME: "",
        MAIL_PASSWORD: "",
        MAIL_STARTTLS: "false",
        MAIL_SSL_TLS: "false",
        MAIL_SUPPRESS_SEND: "false",
        MAIL_WORKER_POLL_INTERVAL_SECONDS: "1",
      },
    },
    {
      // 跳過 tsc：型別檢查由 frontend job 負責，這裡只要產出可跑的 bundle
      command: `pnpm --dir ../frontend exec vite build && pnpm --dir ../frontend exec vite preview --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: BASE_URL,
      timeout: 180_000,
      // 同上：沿用既有 preview 可能是別的分支的舊 bundle
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // vite preview 沿用 server.proxy：把 /api 轉到上面那個 E2E 後端
        EDMS_API_PROXY_TARGET: API_URL,
        // 明示覆寫會被烤進 bundle 的 VITE_*：shell 環境變數優先於 frontend/.env。
        // 否則開發者若把 VITE_API_BASE_URL 設成絕對網址（如 dev 後端），瀏覽器會繞過上面的 proxy
        // 直接打 dev 後端 → 測試帳號寫進共用 dev DB，e2e_ 護欄沒有機會介入。
        VITE_API_BASE_URL: "/api",
        VITE_BASE_PATH: "/",
      },
    },
  ],
})
