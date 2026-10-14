import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AuthProvider } from "./AuthProvider"
import { ForceChangePasswordShell } from "./ForceChangePasswordShell"
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
