import { Outlet } from "react-router-dom"

import { LoginOverlay } from "../auth/LoginOverlay"
import { useAuth } from "../auth/useAuth"

/** 根 layout：渲染路由內容；未登入時以登入 overlay 覆蓋（沿 spec「登入 overlay」語意）。 */
export function RootLayout() {
  const { isAuthenticated } = useAuth()
  return (
    <>
      <Outlet />
      {!isAuthenticated && <LoginOverlay />}
    </>
  )
}
