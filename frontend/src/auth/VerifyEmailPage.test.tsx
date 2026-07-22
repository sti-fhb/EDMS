import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { VerifyEmailPage } from "./VerifyEmailPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

function renderVerify(initialUrl: string) {
  return render(
    <ThemeProvider theme={muiTheme}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <Routes>
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/" element={<div>登入頁</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
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
})