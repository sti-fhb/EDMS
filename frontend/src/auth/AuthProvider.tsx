import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"

import { authApi } from "./authService"
import { AuthContext } from "./authContext"
import { setAuthToken, setOnSessionEnded } from "../services/http"
import type { SessionEndReason } from "../services/http"

// 閒置換發（spec_us1 §12）：使用者於到期前仍有操作即靜默換發；持續閒置則讓 token 自然逾時。
// 檢查間隔須小於伺服端 ACCESS_TTL（15 分），確保「活躍中」不會誤逾時。
const RENEW_INTERVAL_MS = 4 * 60 * 1000

// 到期檢查間隔（#741）。
// ⚠️ 判到期用的是**時間戳比對**（`Date.now() >= expiresAt`），不是數計時器觸發幾次——
// 分頁切到背景時瀏覽器會把 interval 節流到一分鐘以上，數次數會漏算。本間隔只決定
// 「發現得多快」，不影響正確性。
const EXPIRY_CHECK_INTERVAL_MS = 15 * 1000

/**
 * 認證狀態 Provider：memory-only token、閒置換發計時器、到期與帳號失效自動登出。
 * token 僅存記憶體（模組變數 + React state），重整即需重新登入。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setTokenState] = useState<string | null>(null)
  const [mustChangePwd, setMustChangePwd] = useState(false)
  const [sessionEndedReason, setSessionEndedReason] = useState<SessionEndReason | null>(null)
  const lastActivityRef = useRef<number>(0)
  /** 目前 token 的到期時點（本機時鐘的毫秒時間戳）；null 代表未登入或不知到期。 */
  const expiresAtRef = useRef<number | null>(null)

  const applyToken = useCallback((next: string | null, expiresInSec?: number) => {
    setAuthToken(next) // 同步 http interceptor 的 Authorization 來源
    setTokenState(next)
    // 後端回的是**相對秒數**（#741），在這裡換算成本機時間戳：使用者電腦時鐘與伺服器
    // 有偏差也不會誤判。若改讀 JWT 的 `exp`（伺服器絕對時間）就會——時鐘快 10 分鐘的
    // 機器一登入就被判定逾時，而那種客訴查不出原因。
    expiresAtRef.current = next === null || expiresInSec === undefined ? null : Date.now() + expiresInSec * 1000
  }, [])

  /** 被動結束工作階段（非使用者自己按登出）：清狀態並記下原因，供登入畫面提示。 */
  const endSession = useCallback(
    (reason: SessionEndReason) => {
      applyToken(null)
      setMustChangePwd(false)
      setSessionEndedReason(reason)
    },
    [applyToken],
  )

  const login = useCallback(
    async (email: string, password: string) => {
      setSessionEndedReason(null)
      const res = await authApi.login({ email, password })
      lastActivityRef.current = Date.now()
      // 先套用新 token（applyToken 同步寫入 http 的 Authorization 來源），再清快取——
      // 順序很重要：clear() 會令使用中的查詢（如側欄 module-summary）立即以新身分重抓，
      // 若在 token 設定前 clear，重抓會搶先送出而未帶新 token（401 / 空資料），側欄 DM 群組因而抓不到。
      // 如此可修正「剛授權卻要等舊快取過期才更新側欄 / 頁籤」，且不會反而抓不到。
      applyToken(res.access_token, res.expires_in)
      queryClient.clear()
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

  // 被動登出：401（憑證失效 / 閒置逾時 / 換發逾限）→ IDLE；
  // 403 DP_AUTH_004 / 005（使用中被停用 / 鎖定）→ DISABLED / LOCKED（#741）。
  // 其餘 403（權限不足）由 interceptor 自行排除，不會走到這裡。
  useEffect(() => {
    setOnSessionEnded(endSession)
    return () => setOnSessionEnded(null)
  }, [endSession])

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
          .then((res) => applyToken(res.access_token, res.expires_in))
          .catch(() => {
            // 換發失敗（逾限 / 失效）已由 response interceptor 觸發 onSessionEnded，此處不重複處置
          })
      }
    }, RENEW_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [token, applyToken])

  // 到期即登出（#741）：使用者完全不操作時原本要等下一次請求收到 401 才回登入畫面，
  // 而不動就不會有請求 —— 畫面因此一直停著，手冊寫的「自動回到登入畫面」從未發生。
  useEffect(() => {
    if (token === null) return
    const timer = window.setInterval(() => {
      const expiresAt = expiresAtRef.current
      if (expiresAt !== null && Date.now() >= expiresAt) endSession("IDLE")
    }, EXPIRY_CHECK_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [token, endSession])

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: token !== null,
      mustChangePwd,
      sessionEndedReason,
      login,
      logout,
      clearMustChangePwd,
    }),
    [token, mustChangePwd, sessionEndedReason, login, logout, clearMustChangePwd],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
