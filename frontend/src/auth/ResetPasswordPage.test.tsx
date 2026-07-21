import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { ResetPasswordPage } from "./ResetPasswordPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

const _NEW_PWD = "Xyz98765!"

function renderReset(entry: string) {
  return render(
    <ThemeProvider theme={muiTheme}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

async function fillReset(user: ReturnType<typeof userEvent.setup>, pwd = _NEW_PWD, confirm = _NEW_PWD) {
  await user.type(screen.getByLabelText("新密碼"), pwd)
  await user.type(screen.getByLabelText("確認新密碼"), confirm)
  await user.click(screen.getByRole("button", { name: "重設密碼" }))
}

describe("ResetPasswordPage", () => {
  it("有效 token + 合規新密碼 → 顯示成功、提供返回登入", async () => {
    renderReset("/reset-password?token=validtoken")
    const user = userEvent.setup()
    await fillReset(user)
    expect(await screen.findByText("密碼已更新，請以新密碼登入")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回登入" })).toBeInTheDocument()
  })

  it("token 失效（後端 DP_PWD_005）→ 顯示錯誤訊息", async () => {
    server.use(
      http.post("/api/reset-password", () =>
        HttpResponse.json({ error_code: "DP_PWD_005", error_message: "連結已失效，請重新申請" }, { status: 400 }),
      ),
    )
    renderReset("/reset-password?token=expiredtoken")
    const user = userEvent.setup()
    await fillReset(user)
    expect(await screen.findByText("連結已失效，請重新申請")).toBeInTheDocument()
  })

  it("兩次不一致 → 前端 Zod 擋下（不送出）", async () => {
    renderReset("/reset-password?token=validtoken")
    const user = userEvent.setup()
    await fillReset(user, _NEW_PWD, "Diff9999!")
    expect(await screen.findByText("兩次輸入之密碼不一致")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重設密碼" })).toBeInTheDocument()
  })

  it("無 token → 顯示連結無效", () => {
    renderReset("/reset-password")
    expect(screen.getByText("連結無效，請重新申請忘記密碼")).toBeInTheDocument()
  })
})
