import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { ActivateAccountPage } from "./ActivateAccountPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

const _PWD = "Xyz98765!"

function renderActivate(entry: string) {
  return render(
    <ThemeProvider theme={muiTheme}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/activate" element={<ActivateAccountPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

async function fill(user: ReturnType<typeof userEvent.setup>, pwd = _PWD, confirm = _PWD) {
  await user.type(screen.getByLabelText("設定密碼"), pwd)
  await user.type(screen.getByLabelText("確認密碼"), confirm)
  await user.click(screen.getByRole("button", { name: "設定密碼並啟用" }))
}

describe("ActivateAccountPage", () => {
  it("有效邀請 token + 合規密碼 → 顯示啟用成功、提供前往登入", async () => {
    renderActivate("/activate?token=invite-tok")
    const user = userEvent.setup()
    await fill(user)
    expect(await screen.findByText("帳號已啟用，請以新密碼登入")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "前往登入" })).toBeInTheDocument()
  })

  it("邀請 token 無效（後端 DP_USER_003）→ 顯示錯誤訊息", async () => {
    server.use(
      http.post("/api/activate-account", () =>
        HttpResponse.json({ error_code: "DP_USER_003", error_message: "邀請連結無效" }, { status: 400 }),
      ),
    )
    renderActivate("/activate?token=bad-tok")
    const user = userEvent.setup()
    await fill(user)
    expect(await screen.findByText("邀請連結無效")).toBeInTheDocument()
  })

  it("兩次不一致 → 前端 Zod 擋下（不送出）", async () => {
    renderActivate("/activate?token=invite-tok")
    const user = userEvent.setup()
    await fill(user, _PWD, "Diff9999!")
    expect(await screen.findByText("兩次輸入之密碼不一致")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "設定密碼並啟用" })).toBeInTheDocument()
  })

  it("無 token → 顯示連結無效", () => {
    renderActivate("/activate")
    expect(screen.getByText("邀請連結無效，請洽管理者重寄")).toBeInTheDocument()
  })
})