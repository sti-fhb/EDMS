import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"

import { authApi } from "./authService"
import { AuthContext } from "./authContext"
import { setAuthToken, setOnUnauthorized } from "../services/http"

// 閒置換發（spec_us1 §12）：使用者於到期前仍有操作即靜默換發；持續閒置則讓 token 自然逾時。
// 檢查間隔須小於伺服端 ACCESS_TTL（15 分），確保「活躍中」不會誤逾時。
const RENEW_INTERVAL_MS = 4 * 60 * 1000

/**
 * 認證狀態 Provider：memory-only token、閒置換發計時器、401 自動登出。
 * token 僅存記憶體（模組變數 + React state），重整即需重新登入。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setTokenState] = useState<string | null>(null)
  const [mustChangePwd, setMustChangePwd] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)
  const lastActivityRef = useRef<number>(0)

  const applyToken = useCallback((next: string | null) => {
    setAuthToken(next) // 同步 http interceptor 的 Authorization 來源
    setTokenState(next)
  }, [])

  const login = useCallback(
    async (email: string, password: string) => {
      setSessionExpired(false)
      const res = await authApi.login({ email, password })
      lastActivityRef.current = Date.now()
      // 清掉上一個 session 的查詢快取，確保新登入者的模組摘要 / 權限等以新身分重新抓取，
      // 避免出現「剛授權卻要等舊快取過期才更新側欄 / 頁籤」（授權後重登入 DM 畫面延遲顯示）。
      queryClient.clear()
      applyToken(res.access_token)
      setMustChangePwd(res.must_change_pwd)
    },
    [applyToken, queryClient],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // 登出 API 失敗（如網路 / 已逾時）仍清除本地狀態，確保使用者確實登出
    }
    applyToken(null)
    setMustChangePwd(false)
    queryClient.clear() // 清快取，避免下一位登入者短暫看到前一位的資料
  }, [applyToken, queryClient])

  // US8：強制變更頁完成密碼變更後清旗標，RootLayout 即撤下頁殼、放行一般功能（不需重登）。
  const clearMustChangePwd = useCallback(() => setMustChangePwd(false), [])

  // 401（憑證失效 / 閒置逾時 / 換發逾限）→ 清狀態並提示重新登入（DP-MSG-LOGIN-006）。
  useEffect(() => {
    setOnUnauthorized(() => {
      applyToken(null)
      setMustChangePwd(false)
      setSessionExpired(true)
    })
    return () => setOnUnauthorized(null)
  }, [applyToken])

  // 記錄使用者操作時間，供換發計時器判斷「活躍中」。
  useEffect(() => {
    if (token === null) return
    const mark = () => {
      lastActivityRef.current = Date.now()
    }
    window.addEventListener("mousedown", mark)
    window.addEventListener("keydown", mark)
    return () => {
      window.removeEventListener("mousedown", mark)
      window.removeEventListener("keydown", mark)
    }
  }, [token])

  // 閒置換發計時器：到期前若近期有操作則靜默換發；換發失敗（401）由 interceptor 收斂為自動登出。
  useEffect(() => {
    if (token === null) return
    const timer = window.setInterval(() => {
      if (Date.now() - lastActivityRef.current < RENEW_INTERVAL_MS) {
        authApi
          .renew()
          .then((res) => applyToken(res.access_token))
          .catch(() => {
            // 換發失敗（逾限 / 失效）已由 response interceptor 觸發 onUnauthorized，此處不重複處置
          })
      }
    }, RENEW_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [token, applyToken])

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: token !== null,
      mustChangePwd,
      sessionExpired,
      login,
      logout,
      clearMustChangePwd,
    }),
    [token, mustChangePwd, sessionExpired, login, logout, clearMustChangePwd],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
