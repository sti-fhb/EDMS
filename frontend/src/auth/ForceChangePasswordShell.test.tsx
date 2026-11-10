import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AuthProvider } from "./AuthProvider"
import { ForceChangePasswordShell } from "./ForceChangePasswordShell"
import { LoginOverlay } from "./LoginOverlay"
import { useAuth } from "./useAuth"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter>
          <AuthProvider>
            <ForceChangePasswordShell />
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

/**
 * 需要「真的登入過」的情境用這一組（#941）：`renderShell` 直接渲染頁殼、`isAuthenticated`
 * 恆為 false，看不出「變更後回到登入頁」這件事。此處比照 `RootLayout`：未登入即改渲染
 * `LoginOverlay`，於是登出與提示文案都是從使用者看得到的畫面去斷言。
 */
function ShellHarness() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  return (
    <>
      <div data-testid="status">{isAuthenticated ? "authed" : "anon"}</div>
      {!isAuthenticated && <LoginOverlay />}
      {isAuthenticated && mustChangePwd && <ForceChangePasswordShell />}
    </>
  )
}

function renderShellWithLogin() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter>
          <AuthProvider>
            <ShellHarness />
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

async function login(user: ReturnType<typeof userEvent.setup>, { mustChange }: { mustChange: boolean }) {
  server.use(
    http.post("/api/login", () =>
      HttpResponse.json({ access_token: "test-access-token", must_change_pwd: mustChange, expires_in: 900 }),
    ),
  )
  await user.type(screen.getByLabelText("帳號（Email）"), "u@edms.local")
  await user.type(screen.getByLabelText("密碼"), "Abcd1234")
  await user.click(screen.getByRole("button", { name: "登入" }))
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authed"))
}

describe("ForceChangePasswordShell 強制變更密碼（US8 填實提交）", () => {
  it("提供舊 / 新 / 確認欄位，變更密碼按鈕可提交（非 US1 停用狀態）", () => {
    renderShell()
    expect(screen.getByLabelText("舊密碼")).toBeInTheDocument()
    expect(screen.getByLabelText("新密碼")).toBeInTheDocument()
    expect(screen.getByLabelText("確認新密碼")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "變更密碼" })).toBeEnabled()
  })

  it("管理者密碼到期（#623）：提示與前端檢核依本人適用門檻 12 字元，9 字元被擋下、不送出", async () => {
    let submitted = false
    server.use(
      http.get("/api/dp/user/me/password-policy", () => HttpResponse.json({ min_len: 12, char_types: 3 })),
      http.put("/api/dp/user/me/password", () => {
        submitted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderShell()

    // 公開政策端點仍回一般門檻 8：提示若出現 12，代表確實改讀本人適用的門檻
    expect(await screen.findByText(/至少 12 字元/)).toBeInTheDocument()
    await user.type(screen.getByLabelText("舊密碼"), "Abcd1234")
    await user.type(screen.getByLabelText("新密碼"), "Abcd1234!")
    await user.type(screen.getByLabelText("確認新密碼"), "Abcd1234!")
    await user.click(screen.getByRole("button", { name: "變更密碼" }))

    expect(await screen.findByText("密碼至少 12 字元")).toBeInTheDocument()
    expect(submitted).toBe(false)
  })

  it("合規密碼提交 → 呼叫端點成功、不顯示錯誤", async () => {
    const user = userEvent.setup()
    renderShell()
    await user.type(screen.getByLabelText("舊密碼"), "Abcd1234")
    await user.type(screen.getByLabelText("新密碼"), "Xyz98765!")
    await user.type(screen.getByLabelText("確認新密碼"), "Xyz98765!")
    await user.click(screen.getByRole("button", { name: "變更密碼" }))
    await waitFor(() => expect(screen.queryByRole("alert")).not.toHaveTextContent(/失敗|錯誤|不正確/))
  })

  it("完成強制變更 → 回到登入頁並提示密碼已更新，不顯示閒置逾時（#941）", async () => {
    const user = userEvent.setup()
    renderShellWithLogin()
    await login(user, { mustChange: true })

    await user.type(await screen.findByLabelText("舊密碼"), "Abcd1234")
    await user.type(screen.getByLabelText("新密碼"), "Xyz98765!")
    await user.type(screen.getByLabelText("確認新密碼"), "Xyz98765!")
    await user.click(screen.getByRole("button", { name: "變更密碼" }))

    // 回到登入頁：舊 token 在變更當下即失效，沿用它進主頁會被後端 401
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anon"))
    expect(await screen.findByText("密碼已更新，請以新密碼重新登入")).toBeInTheDocument()
    // ⛔ 不得顯示「閒置逾時」：那是被動登出的文案。若實作改成呼叫 /dp/user/logout，
    // 該請求會帶著已失效的舊 token 拿到 401，被 interceptor 收斂成 IDLE 而蓋掉正確訊息。
    expect(screen.queryByText(/閒置逾時/)).not.toBeInTheDocument()
  })

  it("舊密碼錯（422 DP_PWD_006，非 401）→ 顯示錯誤訊息、不觸發自動登出", async () => {
    // 舊密碼錯刻意用 422 而非 401：401 於 http interceptor 代表 session 失效會自動登出、吞掉此訊息
    server.use(
      http.put("/api/dp/user/me/password", () =>
        HttpResponse.json({ error_code: "DP_PWD_006", error_message: "舊密碼不正確" }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderShell()
    await user.type(screen.getByLabelText("舊密碼"), "WrongOld9")
    await user.type(screen.getByLabelText("新密碼"), "Xyz98765!")
    await user.type(screen.getByLabelText("確認新密碼"), "Xyz98765!")
    await user.click(screen.getByRole("button", { name: "變更密碼" }))
    expect(await screen.findByText("舊密碼不正確")).toBeInTheDocument()
  })
})
