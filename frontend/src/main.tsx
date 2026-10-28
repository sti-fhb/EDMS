import createCache from "@emotion/cache"
import { CacheProvider } from "@emotion/react"
import CssBaseline from "@mui/material/CssBaseline"
import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"

import { AuthProvider } from "./auth/AuthProvider"
import { NotificationProvider } from "./contexts/NotificationContext"
import { router } from "./router"
import { readCspNonce } from "./styles/cspNonce"
import { muiTheme } from "./styles/muiTheme"

const queryClient = new QueryClient()

// Emotion 注入的 <style> 帶 CSP nonce：CSP style-src 不放行 'unsafe-inline'（見 styles/cspNonce.ts）。
// 包在最外層，使所有 MUI／Emotion 樣式都經此 cache 注入。
const emotionCache = createCache({ key: "css", nonce: readCspNonce() })

const rootEl = document.getElementById("root")
if (!rootEl) {
  throw new Error("找不到 #root 掛載節點")
}

createRoot(rootEl).render(
  <StrictMode>
    <CacheProvider value={emotionCache}>
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
    </CacheProvider>
  </StrictMode>,
)
