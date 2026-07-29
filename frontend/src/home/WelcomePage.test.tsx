import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { WelcomePage } from "./WelcomePage"
import { AuthContext } from "../auth/authContext"
import type { AuthState } from "../auth/authContext"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

/** WelcomePage 依 useAuth.isAuthenticated 決定是否發 getMe / version（避免未登入時無謂 401）。 */
function makeAuth(isAuthenticated: boolean): AuthState {
  return {
    token: isAuthenticated ? "t" : null,
    isAuthenticated,
    mustChangePwd: false,
    sessionExpired: false,
    login: async () => {},
    logout: async () => {},
    clearMustChangePwd: () => {},
  }
}

function renderWelcome({ isAuthenticated = true }: { isAuthenticated?: boolean } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <AuthContext.Provider value={makeAuth(isAuthenticated)}>
          <WelcomePage />
        </AuthContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe("WelcomePage", () => {
  it("已登入 → 顯示帶姓名問候、系統定位、版本", async () => {
    renderWelcome()
    expect(await screen.findByText("歡迎，測試員")).toBeInTheDocument()
    expect(screen.getByText("教育訓練與文件管理系統")).toBeInTheDocument()
    expect(await screen.findByText("版本 1.0.0-test")).toBeInTheDocument()
  })

  it("姓名 / 版本載入失敗 → 問候退回「歡迎」、隱藏版本行（靜默保底）", async () => {
    server.use(
      http.get("/api/dp/user/me", () => new HttpResponse(null, { status: 500 })),
      http.get("/api/version", () => new HttpResponse(null, { status: 500 })),
    )
    renderWelcome()
    expect(await screen.findByText("歡迎")).toBeInTheDocument()
    expect(screen.getByText("教育訓練與文件管理系統")).toBeInTheDocument()
    expect(screen.queryByText(/^版本/)).not.toBeInTheDocument()
  })

  it("未登入 → 不發 getMe / version（enabled 關）、問候退回「歡迎」", async () => {
    let meRequested = false
    server.use(
      http.get("/api/dp/user/me", () => {
        meRequested = true
        return HttpResponse.json({ user_id: "u1", email: "x@e.local", user_name: "測試員", pending_email: null })
      }),
    )
    renderWelcome({ isAuthenticated: false })
    expect(await screen.findByText("歡迎")).toBeInTheDocument()
    expect(meRequested).toBe(false)
  })
})
