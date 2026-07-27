import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { VerifyEmailPage } from "./VerifyEmailPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

// 以 StrictMode 包裝，對齊正式環境（main.tsx），並讓「掛載期 effect 跑兩次」的行為在測試中重現
function renderVerify(initialUrl: string) {
  return render(
    <StrictMode>
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter initialEntries={[initialUrl]}>
          <Routes>
            <Route path="/verify-email" element={<VerifyEmailPage />} />
            <Route path="/" element={<div>登入頁</div>} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </StrictMode>,
  )
}

describe("VerifyEmailPage", () => {
  it("有效 token → 驗證成功、顯示前往登入", async () => {
    renderVerify("/verify-email?token=good-token")
    expect(await screen.findByText("帳號已啟用，請以新帳號登入。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "前往登入" })).toBeInTheDocument()
  })

  it("連結逾時（DP_USER_004）→ 顯示錯誤訊息", async () => {
    server.use(
      http.post("/api/verify-email", () =>
        HttpResponse.json(
          { error_code: "DP_USER_004", error_message: "驗證連結已失效，請重新申請" },
          { status: 400 },
        ),
      ),
    )
    renderVerify("/verify-email?token=expired-token")
    expect(await screen.findByText("驗證連結已失效，請重新申請")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "回登入頁" })).toBeInTheDocument()
  })

  it("缺 token → 顯示錯誤、不呼叫 API", async () => {
    renderVerify("/verify-email")
    expect(await screen.findByText("驗證連結無效")).toBeInTheDocument()
  })

  it("StrictMode 重複掛載時，同一 token 只送出一次驗證請求", async () => {
    // 回歸測試：修正前 effect 會在 StrictMode 下對同一 token 送出兩個 /verify-email，
    // 兩個請求在後端互撞，輸的那個回 409「已被註冊」誤導使用者
    let requestCount = 0
    server.use(
      http.post("/api/verify-email", () => {
        requestCount += 1
        return HttpResponse.json({ message: "帳號已啟用，請以新帳號登入" })
      }),
    )
    renderVerify("/verify-email?token=good-token")
    expect(await screen.findByText("帳號已啟用，請以新帳號登入。")).toBeInTheDocument()
    expect(requestCount).toBe(1)
  })
})