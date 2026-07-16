import { createContext } from "react"

export interface AuthState {
  /** 目前的存取 token；null 代表未登入。骨架階段僅前端狀態，尚未接後端。 */
  token: string | null
  setToken: (token: string | null) => void
  isAuthenticated: boolean
}

export const AuthContext = createContext<AuthState | undefined>(undefined)
