import { Outlet } from "react-router-dom"

import { ForceChangePasswordShell } from "../auth/ForceChangePasswordShell"
import { LoginOverlay } from "../auth/LoginOverlay"
import { useAuth } from "../auth/useAuth"

/**
 * 根 layout：**登入後才渲染路由內容**（Outlet）；未登入時只顯示登入 overlay；
 * 已登入但須變更密碼者以強制變更頁殼覆蓋（未完成變更不得存取其他功能，spec_us1 §11）。
 *
 * 為何不「先渲染 Outlet 再蓋 overlay」：AppShell 常駐側欄會在未登入時就掛載並呼叫
 * `useModuleSummary`（GET /dp/user/module-summary），此時尚無 token → 401；且該 query error 後
 * 側欄常駐不重掛、不會自動重抓，登入後側欄的模組摘要永遠停在錯誤 → DM 功能群組不顯示。
 * 改為登入後才掛 Outlet/AppShell，module-summary 於登入後才以帶 token 之請求抓一次（200），
 * 側欄即正確反映權限。URL 仍由 router 保留（#89「登入後落在原本開啟的頁」不受影響）。
 */
export function RootLayout() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  if (!isAuthenticated) return <LoginOverlay />
  return (
    <>
      <Outlet />
      {mustChangePwd && <ForceChangePasswordShell />}
    </>
  )
}
