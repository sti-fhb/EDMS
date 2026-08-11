// 【驗證用，不會合併】此註解僅為觸發 CI 的 frontend job，實測 PR #147 升級後的
// pnpm/action-setup@v6.0.10 與 actions/setup-node@v7.0.0 能否正常運作。
// paths-filter 只看 backend/** 與 frontend/**，故 #147 單改 .github/ 時兩個 job
// 都被 skip，新版 action 從未被實際執行過。

import CssBaseline from "@mui/material/CssBaseline"
import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"

import { AuthProvider } from "./auth/AuthProvider"
import { NotificationProvider } from "./contexts/NotificationContext"
import { router } from "./router"
import { muiTheme } from "./styles/muiTheme"

const queryClient = new QueryClient()

const rootEl = document.getElementById("root")
if (!rootEl) {
  throw new Error("找不到 #root 掛載節點")
}

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <CssBaseline />
        <NotificationProvider>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </NotificationProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
