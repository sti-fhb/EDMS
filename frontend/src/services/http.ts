import axios from "axios"
import type { AxiosError } from "axios"

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "/api"

/** 全專案唯一 HTTP client。頁面 / service 一律經此，禁止裸呼叫 fetch / axios。 */
export const http = axios.create({ baseURL })

// memory-only access token：僅存模組變數（重整即失效），不落 localStorage 以降低 XSS 竊取風險。
// 由 AuthProvider 於登入 / 換發 / 登出時以 setAuthToken 同步。
let authToken: string | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

/**
 * 被動登出的原因——交由 `AuthProvider` 轉成登入畫面的提示文案（#741）。
 *
 * `IDLE` 涵蓋 401 的全部情形（憑證無效 / 逾時 / 換發逾限），沿用原本的「閒置逾時」文案。
 */
export type SessionEndReason = "IDLE" | "DISABLED" | "LOCKED"

/**
 * 🔴 **會觸發自動登出的 403 只有這兩個** —— 它們代表「帳號本身不能再用」，與
 * 「這個帳號沒有這項權限」不同。其餘 403（如 `DP_AUTH_006` 需模組管理者、各模組的
 * 無權限）**不得**登出，否則使用者點到一個沒權限的功能就會被踢回登入頁。
 *
 * ⛔ 新增成員前先問：這個錯誤碼是不是「整個帳號失效」？是權限不足就不屬於這裡。
 */
const ACCOUNT_BLOCKED_CODES: Record<string, SessionEndReason> = {
  DP_AUTH_004: "DISABLED", // 帳號已停用
  DP_AUTH_005: "LOCKED", // 帳號已鎖定
}

// 被動登出統一處置回呼：由 AuthProvider 註冊為「清狀態 + 依原因提示」。
let onSessionEnded: ((reason: SessionEndReason) => void) | null = null

export function setOnSessionEnded(handler: ((reason: SessionEndReason) => void) | null): void {
  onSessionEnded = handler
}

http.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // 僅在「已持有 token」時觸發自動登出，避免登入端點的失敗（帳密錯誤 401 / 帳號停用 403）
    // 被誤判為工作階段結束——那時本來就還沒登入。
    if (authToken && onSessionEnded) {
      const status = error.response?.status
      if (status === 401) {
        onSessionEnded("IDLE")
      } else if (status === 403) {
        // 使用中被管理者停用 / 鎖定：後端每請求查 DP_USER 狀態，下一次請求即回這兩碼（#741）。
        // 查表未命中（其他 403 = 權限不足）→ 不登出，只讓呼叫端自己顯示錯誤。
        const code = (error.response?.data as { error_code?: string } | undefined)?.error_code
        const reason = code === undefined ? undefined : ACCOUNT_BLOCKED_CODES[code]
        if (reason !== undefined) onSessionEnded(reason)
      }
    }
    return Promise.reject(error)
  },
)

export interface ApiError {
  status: number
  errorCode: string
  errorMessage: string
  /** 限流 / 冷卻類 429 的可重試剩餘秒數（後端 body 帶回），供前端倒數；無則 undefined。 */
  retryAfter?: number
  /**
   * 錯誤回應的原始 body，供帶結構化細節的錯誤取用。
   *
   * 對應後端 `AppError.extra`（`app/core/exceptions.py`）——例如 ET 發布檢核未通過時
   * 的 `blockers` 清單（`ET_PUBLISH_001`）。取用前**務必先確認 `errorCode`**，不同
   * 錯誤碼的 body 形狀不同，直接讀欄位會在別的錯誤路徑上拿到 undefined。
   *
   * 只有 body 為物件時才有值（非 JSON 的錯誤頁為 undefined）。`retryAfter` 早於本
   * 欄位存在且已有多處呼叫端，維持獨立欄位不併入。
   */
  payload?: Record<string, unknown>
}

/**
 * 把 axios 例外正規化為 `{ status, errorCode, errorMessage, retryAfter }`，供頁面顯示。
 *
 * ## 三種情形要分開，不能都說「連線異常」
 *
 * | 情形 | 判準 | 訊息 |
 * |------|------|------|
 * | 真的連不上 | **完全沒有 response**（斷網、後端沒起來、CORS 被擋）| 系統連線異常 |
 * | 後端正常回報的業務錯誤 | body 有 `error_message` | 原樣顯示 |
 * | 伺服器端出錯 | 有 response 但 body 無 `error_message`（未處理例外之 5xx、反向代理錯誤頁）| 伺服器處理失敗（HTTP xxx）|
 *
 * 原本第三種也顯示「系統連線異常」，會把人帶去查網路——2026-08-26 於 #203 實測時
 * 就發生過：開發庫少套一支 migration 造成 500，畫面只說連線異常，實際上網路好得很。
 * 訊息帶上 HTTP 狀態碼，回報問題時才有東西可講。
 *
 * FastAPI 的未處理例外回的是 `{"detail": "Internal Server Error"}`——沒有
 * `error_message`，正好落在第三種。
 */
export function toApiError(err: unknown): ApiError {
  const axiosErr = err as AxiosError<{ error_code?: string; error_message?: string; retry_after?: number }>
  const response = axiosErr.response
  if (!response) {
    return { status: 0, errorCode: "NETWORK_ERROR", errorMessage: "系統連線異常，請稍後再試" }
  }
  const data = response.data
  if (data?.error_message) {
    return {
      status: response.status,
      errorCode: data.error_code ?? "UNKNOWN_ERROR",
      errorMessage: data.error_message,
      retryAfter: data.retry_after,
      payload: typeof data === "object" ? (data as Record<string, unknown>) : undefined,
    }
  }
  return {
    status: response.status,
    errorCode: "SERVER_ERROR",
    errorMessage: `伺服器處理失敗（HTTP ${response.status}），請稍後再試或聯絡系統管理員`,
  }
}

/**
 * 解析 `responseType: "blob"` 請求的錯誤回應。此類請求失敗時 `response.data` 是 Blob，
 * `toApiError` 取不到 `error_message` 會一律落回「系統連線異常」而掩蓋真因；此函式先把 Blob
 * 讀成文字再解析出後端錯誤碼 / 訊息（如 DM_DOC_001 查無檔案）。非 JSON body 則落回 `toApiError`。
 */
export async function toBlobApiError(err: unknown): Promise<ApiError> {
  const axiosErr = err as AxiosError
  const data = axiosErr.response?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { error_code?: string; error_message?: string; retry_after?: number }
      if (parsed.error_message) {
        return {
          status: axiosErr.response?.status ?? 0,
          errorCode: parsed.error_code ?? "UNKNOWN_ERROR",
          errorMessage: parsed.error_message,
          retryAfter: parsed.retry_after,
        }
      }
      // 是 JSON 但沒有結構化錯誤 → 與一般路徑同樣視為伺服器端出錯
    } catch {
      // 非 JSON（如 HTML 錯誤頁）→ 落回一般處理
    }
  }
  return toApiError(err)
}
