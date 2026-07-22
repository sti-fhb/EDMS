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
