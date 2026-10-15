import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { ResetPasswordPage } from "./ResetPasswordPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

const _NEW_PWD = "Xyz98765!"

/** @param basename 部署 base path（如 "/edms"）；給了就模擬部署環境的 router（#607）。 */
function renderReset(entry: string, basename?: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter basename={basename} initialEntries={[`${basename ?? ""}${entry}`]}>
          <Routes>
            <Route path="/reset-password" element={<ResetPasswordPage />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

async function fillReset(user: ReturnType<typeof userEvent.setup>, pwd = _NEW_PWD, confirm = _NEW_PWD) {
  await user.type(screen.getByLabelText("新密碼"), pwd)
  await user.type(screen.getByLabelText("確認新密碼"), confirm)
  await user.click(screen.getByRole("button", { name: "重設密碼" }))
}

describe("ResetPasswordPage", () => {
  it("密碼規則提示依 PWD_POLICY 動態（#77）：改回傳值 → 提示數字跟著變", async () => {
    // #623 起重設頁改讀「本 token 帳號適用之門檻」端點，不再讀公開政策
    server.use(http.post("/api/reset-password/policy", () => HttpResponse.json({ min_len: 12, char_types: 4 })))
    renderReset("/reset-password?token=validtoken")
    expect(await screen.findByText(/至少 12 字元.*至少 4 種/)).toBeInTheDocument()
  })

  it("前端驗證依 PWD_POLICY 動態（#77）：policy 要求 12 字元時，舊規則合規的 8 字元密碼被 Zod 擋下、不呼叫 API", async () => {
    server.use(http.post("/api/reset-password/policy", () => HttpResponse.json({ min_len: 12, char_types: 3 })))
    const user = userEvent.setup()
    renderReset("/reset-password?token=validtoken")
    // 先等政策載入（提示顯示 12），確保送出時工廂用的是新門檻而非 fallback 8
    await screen.findByText(/至少 12 字元/)
    // "Abcd123!" = 8 字元、3 種字元組合：舊門檻(8)合規，但新門檻(12)不足
    await fillReset(user, "Abcd123!", "Abcd123!")
    expect(await screen.findByText("密碼至少 12 字元")).toBeInTheDocument()
    // 被前端擋下 → 不會出現成功訊息（未呼叫 API）
    expect(screen.queryByText("密碼已更新，請以新密碼登入")).not.toBeInTheDocument()
  })

  it("依信中 token 取該帳號適用門檻（#623）：管理者顯示 12 字元，送出的 token 與網址一致", async () => {
    let sentToken: string | null = null
    server.use(
      http.post("/api/reset-password/policy", async ({ request }) => {
        sentToken = ((await request.json()) as { token: string }).token
        return HttpResponse.json({ min_len: 12, char_types: 3 })
      }),
    )
    renderReset("/reset-password?token=admin-token")
    // 公開政策端點仍回一般門檻 8：提示若出現 12，代表確實改讀 token 帳號適用的門檻
    expect(await screen.findByText(/至少 12 字元/)).toBeInTheDocument()
    expect(sentToken).toBe("admin-token")
  })

  it("有效 token + 合規新密碼 → 顯示成功、提供返回登入", async () => {
    renderReset("/reset-password?token=validtoken")
    const user = userEvent.setup()
    await fillReset(user)
    expect(await screen.findByText("密碼已更新，請以新密碼登入")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回登入" })).toBeInTheDocument()
  })

  it("部署於子路徑（/edms）時，「返回登入」指向 /edms 而非網域根目錄（#607）", async () => {
    renderReset("/reset-password?token=validtoken", "/edms")
    const user = userEvent.setup()
    await fillReset(user)
    expect(await screen.findByRole("link", { name: "返回登入" })).toHaveAttribute("href", "/edms")
  })

  // #673 之後這條仍然到得了：門檻端點放行（token 當下有效）、使用者打完密碼期間才逾期。
  // 此處只 mock 送出端點，門檻端點走 server.ts 的預設 200，故表單照常渲染。
  it("token 於填表期間失效（送出時後端回 DP_PWD_005）→ 顯示錯誤訊息", async () => {
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

  it("連結已逾期（門檻端點回 DP_PWD_005）→ 點連結即提示失效，不渲染重設表單（#673）", async () => {
    server.use(
      http.post("/api/reset-password/policy", () =>
        HttpResponse.json({ error_code: "DP_PWD_005", error_message: "連結已失效，請重新申請" }, { status: 400 }),
      ),
    )
    renderReset("/reset-password?token=expiredtoken")
    // 正向錨點：失效訊息必須出現——證明下面兩條否定斷言是在有東西可驗的情況下成立
    expect(await screen.findByText("連結已失效，請重新申請")).toBeInTheDocument()
    // 不得再讓使用者照著門檻打完一組密碼才被擋下（本 issue 的回報症狀）
    expect(screen.queryByLabelText("新密碼")).not.toBeInTheDocument()
    expect(screen.queryByText(/至少 \d+ 字元/)).not.toBeInTheDocument()
  })

  it("門檻端點被限流（429）→ 不報出任何字數、也不誤判成連結失效（#673）", async () => {
    server.use(
      http.post("/api/reset-password/policy", () =>
        HttpResponse.json({ error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試" }, { status: 429 }),
      ),
    )
    renderReset("/reset-password?token=validtoken")
    // 正向錨點：確實走到「取不到門檻」這個狀態，而不是停在載入中
    expect(await screen.findByText(/無法取得密碼規則/)).toBeInTheDocument()
    // 連結可能是好的 → 表單仍須可用，不得擋人
    expect(screen.getByLabelText("新密碼")).toBeInTheDocument()
    // ⛔ 不得掉回寫死的「至少 8 字元」——管理者實際門檻是 12，那是 #623 修掉的矛盾
    expect(screen.queryByText(/至少 \d+ 字元/)).not.toBeInTheDocument()
    // 429 不代表連結壞了，說錯比不說更糟
    expect(screen.queryByText("連結已失效，請重新申請")).not.toBeInTheDocument()
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
