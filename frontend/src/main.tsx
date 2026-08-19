// 【驗證用，不會合併】此註解僅為觸發 CI 的 frontend job，實測 PR #173 升級後的
// dorny/paths-filter@v4.0.3 是否仍能正確判定「有變更」（其失效方式是靜默的：
// 若恆回傳 false，所有 job 會安靜 skip、CI 綠得毫無意義）。

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
