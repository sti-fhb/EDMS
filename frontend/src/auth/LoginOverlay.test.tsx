import { ThemeProvider } from "@mui/material/styles"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { AuthProvider } from "./AuthProvider"
import { LoginOverlay } from "./LoginOverlay"
import { useAuth } from "./useAuth"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

function Harness() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  const status = !isAuthenticated ? "anon" : mustChangePwd ? "must-change" : "authed"
  return (
    <>
      <div data-testid="status">{status}</div>
      {!isAuthenticated && <LoginOverlay />}
      {isAuthenticated && mustChangePwd && <div>強制變更頁殼</div>}
    </>
  )
}

function renderLogin() {
  return render(
    <ThemeProvider theme={muiTheme}>
      <AuthProvider>
        <Harness />
      </AuthProvider>
    </ThemeProvider>,
  )
}

async function submitLogin() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText("帳號（Email）"), "u@edms.local")
  await user.type(screen.getByLabelText("密碼"), "Abcd1234")
  await user.click(screen.getByRole("button", { name: "登入" }))
}

describe("LoginOverlay", () => {
  it("帳密正確 → 登入成功、overlay 撤除", async () => {
    renderLogin()
    await submitLogin()
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authed"))
  })

  it("密碼錯誤 → 顯示錯誤訊息、維持未登入", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ error_code: "DP_AUTH_008", error_message: "密碼錯誤" }, { status: 401 }),
      ),
    )
    renderLogin()
    await submitLogin()
    expect(await screen.findByText("密碼錯誤")).toBeInTheDocument()
    expect(screen.getByTestId("status")).toHaveTextContent("anon")
  })

  it("查無帳號 → 顯示訊息並提供註冊入口", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json(
          { error_code: "DP_AUTH_007", error_message: "查無此帳號，請先註冊" },
          { status: 401 },
        ),
      ),
    )
    renderLogin()
    await submitLogin()
    expect(await screen.findByText("查無此帳號，請先註冊")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "前往註冊" })).toBeInTheDocument()
  })

  it("須變更密碼 → 登入成功但進強制變更頁殼", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ access_token: "t", must_change_pwd: true }),
      ),
    )
    renderLogin()
    await submitLogin()
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("must-change"))
    expect(screen.getByText("強制變更頁殼")).toBeInTheDocument()
  })
})
