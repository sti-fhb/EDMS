import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render } from "@testing-library/react"
import type { RenderOptions } from "@testing-library/react"
import type { ReactElement, ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"

import { NotificationProvider } from "../contexts/NotificationContext"
import { muiTheme } from "../styles/muiTheme"

/**
 * 測試用 render：包 MUI Theme + TanStack Query + Notification + Router。
 * 每次呼叫建立獨立 QueryClient（關閉 retry），避免測試間快取污染。
 */
export function renderWithProviders(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={muiTheme}>
          <NotificationProvider>
            <MemoryRouter>{children}</MemoryRouter>
          </NotificationProvider>
        </ThemeProvider>
      </QueryClientProvider>
    )
  }

  return render(ui, { wrapper: Wrapper, ...options })
}
