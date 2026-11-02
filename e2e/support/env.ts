/**
 * E2E 環境常數：playwright.config.ts 與各支測試共用的單一事實來源。
 *
 * ⚠️ 本 repo 為 public：這裡只放 CI 用的假值（帳密 `edms/edms`、假 JWT 密鑰）。
 * 本機若帳密不同，用環境變數覆寫（見 e2e/README.md），**不要**把真實帳密寫進來。
 *
 * Port 刻意與 dev（後端 8001 / 前端 5174）錯開：手上開著 dev server 也能跑 E2E，
 * 而且 E2E 絕不會誤連 dev 後端 → 誤寫共用 dev DB。
 */

const intFromEnv = (name: string, fallback: number): number => {
  const raw = process.env[name]
  if (raw === undefined || raw === "") return fallback
  const n = Number(raw)
  if (!Number.isInteger(n) || n <= 0) throw new Error(`${name} 必須是正整數，收到：${raw}`)
  return n
}

export const API_PORT = intFromEnv("E2E_API_PORT", 8101)
export const WEB_PORT = intFromEnv("E2E_WEB_PORT", 4174)

/** 一律走 127.0.0.1：localhost 可能先解析成 IPv6 ::1，而後端只綁 IPv4（同 vite.config.ts 的說明）。 */
export const BASE_URL = `http://127.0.0.1:${WEB_PORT}`
export const API_URL = `http://127.0.0.1:${API_PORT}`

/** mailpit：SMTP 收信 + HTTP API（測試從這裡取驗證 / 重設連結）。 */
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL || "http://127.0.0.1:8025"
export const SMTP_HOST = process.env.E2E_SMTP_HOST || "127.0.0.1"
export const SMTP_PORT = intFromEnv("E2E_SMTP_PORT", 1025)

/**
 * E2E 專用 DB。DB 名**必須以 `e2e_` 開頭**——scripts/start-backend.sh 會擋，
 * 避免誤指到共用 dev DB（`edms`）或 integration test DB（`test_edms*`）而在上面跑 migration、塞測試帳號。
 */
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL || "postgresql+asyncpg://edms:edms@127.0.0.1:5432/e2e_edms"

/** 等信的上限。worker 輪距在 E2E 設 1 秒，正常 1～3 秒內就會到。 */
export const MAIL_WAIT_TIMEOUT_MS = 30_000
