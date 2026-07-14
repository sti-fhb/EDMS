import { useContext } from "react"

import { AuthContext } from "./authContext"
import type { AuthState } from "./authContext"

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (ctx === undefined) {
    throw new Error("useAuth 必須在 <AuthProvider> 內使用")
  }
  return ctx
}
