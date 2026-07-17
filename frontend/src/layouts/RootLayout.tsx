import { Outlet } from "react-router-dom"

import { ForceChangePasswordShell } from "../auth/ForceChangePasswordShell"
import { LoginOverlay } from "../auth/LoginOverlay"
import { useAuth } from "../auth/useAuth"

/**
 * 根 layout：渲染路由內容；未登入時以登入 overlay 覆蓋；
 * 已登入但須變更密碼者以強制變更頁殼覆蓋（未完成變更不得存取其他功能，spec_us1 §11）。
 */
export function RootLayout() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  return (
    <>
      <Outlet />
      {!isAuthenticated && <LoginOverlay />}
      {isAuthenticated && mustChangePwd && <ForceChangePasswordShell />}
    </>
  )
}
