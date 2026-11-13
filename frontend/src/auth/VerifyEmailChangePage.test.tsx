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
    // 正向錨點（#956）：這段說明在「連結失效」情境**要在**。少了它，把整段刪掉也能讓下面那條停用的測試通過
    expect(screen.getByText(/可於個人資料頁重新申請/)).toBeInTheDocument()
  })

  it("帳號已停用（DP_PWD_007）→ 明說停用，且不顯示「重新申請」說明", async () => {
    server.use(
      http.post("/api/verify-email-change", () =>
        HttpResponse.json({ error_code: "DP_PWD_007", error_message: "帳號已停用，請洽管理者" }, { status: 400 }),
      ),
    )
    renderVerify("/verify-email-change?token=disabled-acct")
    expect(await screen.findByText("帳號已停用，請洽管理者")).toBeInTheDocument()
    // 那段寫死的說明在本情境三句全錯：連結仍有效、變更未作廢（#956 擋下時不消費 token）、
    // 而停用帳號登不進去、根本到不了個人資料頁
    expect(screen.queryByText(/可於個人資料頁重新申請/)).not.toBeInTheDocument()
  })

  it("缺 token → 直接顯示錯誤，不呼叫 API", async () => {
    renderVerify("/verify-email-change")
    expect(await screen.findByText("驗證連結無效")).toBeInTheDocument()
  })
})
