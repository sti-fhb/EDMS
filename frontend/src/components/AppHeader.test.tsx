import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AppHeader } from "./AppHeader"
import { AuthContext } from "../auth/authContext"
import type { AuthState } from "../auth/authContext"
import { muiTheme } from "../styles/muiTheme"

const authStub: AuthState = {
  token: "t",
  isAuthenticated: true,
  mustChangePwd: false,
  sessionExpired: false,
  login: async () => {},
  logout: async () => {},
  clearMustChangePwd: () => {},
}

function renderHeader(overrides: Partial<AuthState> = {}) {
  return render(
    <ThemeProvider theme={muiTheme}>
      <AuthContext.Provider value={{ ...authStub, ...overrides }}>
        <MemoryRouter initialEntries={["/profile"]}>
          <Routes>
            <Route path="/profile" element={<AppHeader />} />
            <Route path="/portal" element={<div>主頁</div>} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>,
  )
}

describe("AppHeader 個資選單", () => {
  it("點『個人資料』導向 /profile", async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider theme={muiTheme}>
        <AuthContext.Provider value={authStub}>
          <MemoryRouter initialEntries={["/portal"]}>
            <Routes>
              <Route path="/portal" element={<AppHeader />} />
              <Route path="/profile" element={<div>個人資料頁</div>} />
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      </ThemeProvider>,
    )
    await user.click(screen.getByRole("button", { name: "個資選單" }))
    await user.click(screen.getByRole("menuitem", { name: "個人資料" }))
    expect(await screen.findByText("個人資料頁")).toBeInTheDocument()
  })

  it("登出後導回主頁（避免停在 /profile 深層路由）", async () => {
    const user = userEvent.setup()
    renderHeader()
    await user.click(screen.getByRole("button", { name: "個資選單" }))
    await user.click(screen.getByRole("menuitem", { name: "登出" }))
    expect(await screen.findByText("主頁")).toBeInTheDocument()
  })
})
