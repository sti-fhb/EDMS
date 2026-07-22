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
    // 「前往註冊」為切換至註冊分頁的按鈕（in-page 動作，非導航連結）
    expect(screen.getByRole("button", { name: "前往註冊" })).toBeInTheDocument()
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

  it("未驗證帳號登入（DP_AUTH_010）→ 顯示提示並提供重寄驗證信", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json(
          {
            error_code: "DP_AUTH_010",
            error_message: "此帳號尚未完成 Email 驗證，請至信箱點驗證連結或重新寄送",
          },
          { status: 401 },
        ),
      ),
    )
    renderLogin()
    await submitLogin()
    expect(await screen.findByText(/尚未完成 Email 驗證/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重寄驗證信" })).toBeInTheDocument()
  })

  async function fillRegister(user: ReturnType<typeof userEvent.setup>, over: Partial<Record<string, string>> = {}) {
    await user.click(screen.getByRole("tab", { name: "註冊" }))
    await user.type(screen.getByLabelText("帳號（Email）"), over.email ?? "new@edms.local")
    await user.type(screen.getByLabelText("姓名"), over.user_name ?? "新學員")
    await user.type(screen.getByLabelText("密碼"), over.password ?? "Abcd1234")
    await user.type(screen.getByLabelText("確認密碼"), over.confirm ?? "Abcd1234")
    await user.click(screen.getByRole("button", { name: "建立帳號" }))
  }

  it("註冊成功 → 分頁內顯示「驗證信已寄」+ 重寄（不跳登入、方案 B）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "grad@edms.local" })
    // 顯示已寄至該 Email（不再跳登入分頁）
    expect(await screen.findByText("grad@edms.local")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重寄驗證信" })).toBeInTheDocument()
  })

  it("註冊 Email 重複 → 顯示錯誤訊息（DP_USER_001）", async () => {
    server.use(
      http.post("/api/register", () =>
        HttpResponse.json(
          { error_code: "DP_USER_001", error_message: "此 Email 已被註冊，請直接登入或使用忘記密碼" },
          { status: 409 },
        ),
      ),
    )
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "dup@edms.local" })
    expect(await screen.findByText("此 Email 已被註冊，請直接登入或使用忘記密碼")).toBeInTheDocument()
  })

  it("兩次密碼不一致 → 前端 Zod 擋下（不送出、留在註冊分頁）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { confirm: "Zzzz9999" })
    expect(await screen.findByText("兩次輸入之密碼不一致")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "建立帳號" })).toBeInTheDocument()
  })

  it("忘記密碼 → 送出後顯示統一提示（防列舉）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "忘記密碼？" }))
    await user.type(screen.getByLabelText("帳號（Email）"), "any@edms.local")
    await user.click(screen.getByRole("button", { name: "送出" }))
    expect(
      await screen.findByText("若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"),
    ).toBeInTheDocument()
  })
})
