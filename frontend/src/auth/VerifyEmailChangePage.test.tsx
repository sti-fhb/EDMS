import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { VerifyEmailChangePage } from "./VerifyEmailChangePage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

// StrictMode 包裝對齊正式環境，並讓「掛載期 effect 跑兩次」在測試中重現（驗去重）
function renderVerify(initialUrl: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={muiTheme}>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/verify-email-change" element={<VerifyEmailChangePage />} />
              <Route path="/" element={<div>登入頁</div>} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

describe("VerifyEmailChangePage", () => {
  it("有效 token → 切換成功、顯示前往登入", async () => {
    renderVerify("/verify-email-change?token=good-token")
    expect(await screen.findByText("Email 已變更，請以新 Email 登入。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "前往登入" })).toBeInTheDocument()
  })

  it("連結逾時（DP_PWD_005）→ 顯示 PROFILE-008 錯誤訊息", async () => {
    server.use(
      http.post("/api/verify-email-change", () =>
        HttpResponse.json(
          { error_code: "DP_PWD_005", error_message: "連結已失效，Email 變更作廢，原 Email 維持有效" },
          { status: 400 },
        ),
      ),
    )
    renderVerify("/verify-email-change?token=expired-token")
    expect(await screen.findByText("連結已失效，Email 變更作廢，原 Email 維持有效")).toBeInTheDocument()
  })

  it("缺 token → 直接顯示錯誤，不呼叫 API", async () => {
    renderVerify("/verify-email-change")
    expect(await screen.findByText("驗證連結無效")).toBeInTheDocument()
  })
})
