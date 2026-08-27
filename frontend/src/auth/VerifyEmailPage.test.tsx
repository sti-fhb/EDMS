import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { VerifyEmailPage } from "./VerifyEmailPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

// 以 StrictMode 包裝，對齊正式環境（main.tsx）
function renderVerify(initialUrl: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={muiTheme}>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route path="/" element={<div>登入頁</div>} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

async function setPassword(user: ReturnType<typeof userEvent.setup>, pwd = "Abcd1234", confirm?: string) {
  await user.type(screen.getByLabelText("設定密碼"), pwd)
  await user.type(screen.getByLabelText("確認密碼"), confirm ?? pwd)
  await user.click(screen.getByRole("button", { name: "設定密碼並啟用" }))
}

describe("VerifyEmailPage（設定密碼以完成註冊，#212）", () => {
  it("有效 token + 合規密碼 → 送出後顯示啟用成功", async () => {
    renderVerify("/verify-email?token=good-token")
    const user = userEvent.setup()
    await setPassword(user)
    expect(await screen.findByText("帳號已啟用，請以新密碼登入")).toBeInTheDocument()
  })

  it("密碼隨請求一起送出（後端據此建立帳號，非沿用註冊階段的密碼）", async () => {
    let received: Record<string, unknown> | null = null
    server.use(
      http.post("/api/verify-email", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ message: "帳號已啟用" })
      }),
    )
    renderVerify("/verify-email?token=good-token")
    const user = userEvent.setup()
    await setPassword(user, "Str0ng!Pass")

    expect(await screen.findByText("帳號已啟用，請以新密碼登入")).toBeInTheDocument()
    expect(received).toEqual({
      token: "good-token",
      new_password: "Str0ng!Pass",
      confirm_password: "Str0ng!Pass",
    })
  })

  it("兩次不一致 → 前端 Zod 擋下（不送出、留在表單）", async () => {
    renderVerify("/verify-email?token=good-token")
    const user = userEvent.setup()
    await setPassword(user, "Abcd1234", "Zzzz9999")
    expect(await screen.findByText("兩次輸入之密碼不一致")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "設定密碼並啟用" })).toBeInTheDocument()
  })

  it("連結逾時（DP_USER_004）→ 顯示後端錯誤訊息", async () => {
    server.use(
      http.post("/api/verify-email", () =>
        HttpResponse.json(
          { error_code: "DP_USER_004", error_message: "驗證連結已失效，請重新申請" },
          { status: 400 },
        ),
      ),
    )
    renderVerify("/verify-email?token=expired-token")
    const user = userEvent.setup()
    await setPassword(user)
    expect(await screen.findByText("驗證連結已失效，請重新申請")).toBeInTheDocument()
  })

  it("缺 token → 顯示錯誤、不呈現表單", async () => {
    renderVerify("/verify-email")
    expect(await screen.findByText("驗證連結無效")).toBeInTheDocument()
    expect(screen.queryByLabelText("設定密碼")).not.toBeInTheDocument()
  })
})
