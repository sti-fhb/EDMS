import { createContext } from "react"

import type { SessionEndReason } from "../services/http"

export interface AuthState {
  /** 目前的存取 token；null 代表未登入。memory-only（重整即失效，不落 localStorage）。 */
  token: string | null
  isAuthenticated: boolean
  /** 登入者須先變更密碼（初始密碼 / 逾效期）；true 時應導向強制變更頁殼、擋其他功能。 */
  mustChangePwd: boolean
  /**
   * 被動登出的原因；`null` 代表不是被動登出（從未登入，或使用者自己按登出）。
   *
   * 供登入頁顯示對應提示（#741）。刻意**取代**原本的 `sessionExpired: boolean` 而非並存——
   * 兩個欄位描述同一件事必然漂移，到時沒有任何東西會告訴你它們不一致。
   */
  sessionEndedReason: SessionEndReason | null
  /** 帳密登入；失敗拋 ApiError（由呼叫端顯示訊息）。 */
  login: (email: string, password: string) => Promise<void>
  /** 登出：寫 LOGOUT 稽核（失敗仍清本地狀態）並清除 token。 */
  logout: () => Promise<void>
  /**
   * 密碼變更成功後結束本機工作階段（#941）：清 token 與旗標，登入畫面提示「密碼已更新」。
   *
   * ⛔ **不要改成呼叫 `logout()`**：變更當下舊 token 已被後端判定失效，`logout()` 會先打
   * `/dp/user/logout`、拿到 401，被 interceptor 收斂成被動登出而顯示「閒置逾時」——
   * 使用者剛成功改完密碼卻看到逾時訊息。
   */
  endSessionAfterPasswordChange: () => void
}

export const AuthContext = createContext<AuthState | undefined>(undefined)
