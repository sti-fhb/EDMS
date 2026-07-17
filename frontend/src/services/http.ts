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

// 401（憑證無效 / 逾時 / 換發逾限）統一處置回呼：由 AuthProvider 註冊為「清狀態 + 提示重新登入」。
let onUnauthorized: (() => void) | null = null

export function setOnUnauthorized(handler: (() => void) | null): void {
  onUnauthorized = handler
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
    // 僅在「已持有 token」時對 401 觸發自動登出，避免登入端點回 401（帳密錯誤）被誤判為逾時登出。
    if (error.response?.status === 401 && authToken && onUnauthorized) {
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

export interface ApiError {
  status: number
  errorCode: string
  errorMessage: string
}

/** 把 axios 例外正規化為 { status, errorCode, errorMessage }，供頁面顯示（對齊後端錯誤格式）。 */
export function toApiError(err: unknown): ApiError {
  const axiosErr = err as AxiosError<{ error_code?: string; error_message?: string }>
  return {
    status: axiosErr.response?.status ?? 0,
    errorCode: axiosErr.response?.data?.error_code ?? "NETWORK_ERROR",
    errorMessage: axiosErr.response?.data?.error_message ?? "系統連線異常，請稍後再試",
  }
}
