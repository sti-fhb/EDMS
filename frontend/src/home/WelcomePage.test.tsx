import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { WelcomePage } from "./WelcomePage"
import { AuthContext } from "../auth/authContext"
import type { AuthState } from "../auth/authContext"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

/** WelcomePage 依 useAuth.isAuthenticated 決定是否發 getMe（避免未登入時無謂 401）。 */
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
          <MemoryRouter>
            <WelcomePage />
          </MemoryRouter>
        </AuthContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe("WelcomePage", () => {
  it("已登入 → 顯示帶姓名問候", async () => {
    renderWelcome()
    expect(await screen.findByText("歡迎，測試員")).toBeInTheDocument()
  })

  it("姓名載入失敗 → 問候退回「歡迎」（靜默保底）", async () => {
    server.use(http.get("/api/dp/user/me", () => new HttpResponse(null, { status: 500 })))
    renderWelcome()
    expect(await screen.findByText("歡迎")).toBeInTheDocument()
  })

  /**
   * 2026-10-02 手測裁示：拿掉「系統定位」與版本號。
   *
   * ⚠️ 系統定位文案原是 **#89 的決策 D3**（PO 於 2026-07-28 定案），本次移除屬**刻意
   * 推翻**。這條測試存在的目的就是把那個決定釘在程式碼裡——日後若有人依 #89 的留言
   * 把它加回來，這裡會紅，於是他會先來問，而不是直接改。
   *
   * 📌 版本號本身未消失，登入畫面仍然顯示（`LoginOverlay.test.tsx` 有對應測試）。
   */
  it("不顯示系統定位文案與版本號，也不查 /api/version", async () => {
    let versionRequested = false
    server.use(
      http.get("/api/version", () => {
        versionRequested = true
        return HttpResponse.json({ version: "1.0.0-test" })
      }),
    )
    renderWelcome()

    expect(await screen.findByText("歡迎，測試員")).toBeInTheDocument()
    expect(screen.queryByText("教育訓練與文件管理系統")).not.toBeInTheDocument()
    expect(screen.queryByText(/^版本/)).not.toBeInTheDocument()
    expect(versionRequested).toBe(false)
  })

  it("未登入 → 不發 getMe（enabled 關）、問候退回「歡迎」", async () => {
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

  it("具 DM 角色 → 疊加「DM 文件概況」widget（US7 / #89）", async () => {
    // 預設 module-summary dm.has_role=true
    renderWelcome()
    expect(await screen.findByText("DM 文件概況")).toBeInTheDocument()
    expect(await screen.findByText("各類型文件總數")).toBeInTheDocument()
  })

  it("無 DM 角色 → 不顯示 DM 文件概況 widget（最小知悉）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({ et: { has_role: true }, dm: { has_role: false } }),
      ),
    )
    renderWelcome()
    expect(await screen.findByText("歡迎，測試員")).toBeInTheDocument()
    expect(screen.queryByText("DM 文件概況")).not.toBeInTheDocument()
  })
})
