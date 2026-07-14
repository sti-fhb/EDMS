import { useMemo, useState } from "react"
import type { ReactNode } from "react"

import { AuthContext } from "./authContext"

/**
 * 認證狀態 Provider（骨架）。
 * 目前僅維護前端 token 狀態；實際登入 / JWT / redirect 屬 US1 + T013/T014。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null)

  const value = useMemo(
    () => ({ token, setToken, isAuthenticated: token !== null }),
    [token],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
