import { createContext } from "react"

export interface AuthState {
  /** 目前的存取 token；null 代表未登入。memory-only（重整即失效，不落 localStorage）。 */
  token: string | null
  isAuthenticated: boolean
  /** 登入者須先變更密碼（初始密碼 / 逾效期）；true 時應導向強制變更頁殼、擋其他功能。 */
  mustChangePwd: boolean
  /** 因閒置逾時 / 憑證失效被自動登出；供登入頁顯示「請重新登入」提示。 */
  sessionExpired: boolean
  /** 帳密登入；失敗拋 ApiError（由呼叫端顯示訊息）。 */
  login: (email: string, password: string) => Promise<void>
  /** 登出：寫 LOGOUT 稽核（失敗仍清本地狀態）並清除 token。 */
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthState | undefined>(undefined)
