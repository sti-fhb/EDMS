import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { AuthProvider } from "./AuthProvider"
import { LoginOverlay } from "./LoginOverlay"
import { useAuth } from "./useAuth"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

/**
 * 後端對「查無有效 DP_USER 列」的唯一訊息（#208 `_NO_ACCOUNT_MESSAGE`）。
 *
 * 四種帳號狀態（不存在 / 自助註冊未驗證 / 管理者已邀請 / 待驗證列逾期）共用它，
 * 所以測試裡也只該有這一個字串——若哪天出現第二個，就是後端又把回應分岔回去了。
 */
const NEUTRAL_MESSAGE = "帳號或密碼錯誤。若尚未註冊請先註冊；若剛完成註冊，請至信箱點選驗證連結，未收到信可重新寄送"

function Harness() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  const status = !isAuthenticated ? "anon" : mustChangePwd ? "must-change" : "authed"
  return (
    <>
      <div data-testid="status">{status}</div>
      {!isAuthenticated && <LoginOverlay />}
      {isAuthenticated && mustChangePwd && <div>強制變更頁殼</div>}
    </>
  )
}

function renderLogin() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <AuthProvider>
          <Harness />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

async function submitLogin() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText("帳號（Email）"), "u@edms.local")
  await user.type(screen.getByLabelText("密碼"), "Abcd1234")
  await user.click(screen.getByRole("button", { name: "登入" }))
}

describe("LoginOverlay", () => {
  it("帳密正確 → 登入成功、overlay 撤除", async () => {
    renderLogin()
    await submitLogin()
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authed"))
  })

  it("主標為系統中文名、副標為英文名，並顯示版號（#421 對齊主專案）", async () => {
    renderLogin()
    expect(screen.getByText("教育訓練文件管理系統")).toBeInTheDocument()
    expect(screen.getByText("Education & Document Management System")).toBeInTheDocument()
    // 標題區不再出現縮寫「EDMS」（#421）
    expect(screen.queryByText("EDMS")).not.toBeInTheDocument()
    // 版號取自公開 /api/version（MSW 預設 1.0.0-test）
    expect(await screen.findByText("版本 1.0.0-test")).toBeInTheDocument()
  })

  it("密碼錯誤 → 顯示錯誤訊息、維持未登入、不出現註冊 / 重寄入口", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ error_code: "DP_AUTH_008", error_message: "密碼錯誤" }, { status: 401 }),
      ),
    )
    renderLogin()
    await submitLogin()
    expect(await screen.findByText("密碼錯誤")).toBeInTheDocument()
    expect(screen.getByTestId("status")).toHaveTextContent("anon")
    // 已驗證帳號打錯密碼時給出這兩條路只會誤導；同時確認 DP_AUTH_007 那條不是「永遠都顯示」。
    expect(screen.queryByRole("button", { name: "前往註冊" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "重寄驗證信" })).not.toBeInTheDocument()
  })

  it("查無有效帳號（DP_AUTH_007）→ 同時提供註冊與重寄兩條出路", async () => {
    // #208：後端已不再區分「查無帳號」與「尚未驗證」，前端因此也無從得知該顯示哪一條。
    // 兩條並列由本人選；少任何一條都會讓某一類使用者走進死路。
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ error_code: "DP_AUTH_007", error_message: NEUTRAL_MESSAGE }, { status: 401 }),
      ),
    )
    renderLogin()
    await submitLogin()
    expect(await screen.findByText(NEUTRAL_MESSAGE)).toBeInTheDocument()
    // 兩者皆為 in-page 動作的按鈕（非導航連結）
    expect(screen.getByRole("button", { name: "前往註冊" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重寄驗證信" })).toBeInTheDocument()
  })

  it("長訊息完整顯示、不被截斷（DP_AUTH_007 的中性訊息含三條指引）", async () => {
    // 統一訊息比原本的「查無此帳號，請先註冊」長得多，Alert 內需完整呈現（#208 AC 5）。
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ error_code: "DP_AUTH_007", error_message: NEUTRAL_MESSAGE }, { status: 401 }),
      ),
    )
    renderLogin()
    await submitLogin()
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("尚未註冊請先註冊")
    expect(alert).toHaveTextContent("請至信箱點選驗證連結")
    expect(alert).toHaveTextContent("未收到信可重新寄送")
  })

  it("須變更密碼 → 登入成功但進強制變更頁殼", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ access_token: "t", must_change_pwd: true }),
      ),
    )
    renderLogin()
    await submitLogin()
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("must-change"))
    expect(screen.getByText("強制變更頁殼")).toBeInTheDocument()
  })

  async function fillRegister(user: ReturnType<typeof userEvent.setup>, over: Partial<Record<string, string>> = {}) {
    await user.click(screen.getByRole("tab", { name: "註冊" }))
    await user.type(screen.getByLabelText("帳號（Email）"), over.email ?? "new@edms.local")
    await user.type(screen.getByLabelText("姓名"), over.user_name ?? "新學員")
    await user.click(screen.getByRole("button", { name: "建立帳號" }))
  }

  it("註冊成功 → 分頁內顯示「驗證信已寄」+ 重寄（不跳登入、方案 B）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "grad@edms.local" })
    // 顯示已寄至該 Email（不再跳登入分頁）
    expect(await screen.findByText("grad@edms.local")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重寄驗證信" })).toBeInTheDocument()
  })

  it("註冊 Email 重複 → 顯示錯誤訊息（DP_USER_001）", async () => {
    server.use(
      http.post("/api/register", () =>
        HttpResponse.json(
          { error_code: "DP_USER_001", error_message: "此 Email 已被註冊，請直接登入或使用忘記密碼" },
          { status: 409 },
        ),
      ),
    )
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "dup@edms.local" })
    expect(await screen.findByText("此 Email 已被註冊，請直接登入或使用忘記密碼")).toBeInTheDocument()
  })

  it("註冊表單不含密碼欄位（密碼於驗證頁設定，#212）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "註冊" }))
    expect(screen.queryByLabelText("密碼")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("確認密碼")).not.toBeInTheDocument()
  })

  it("姓名未填 → 前端 Zod 擋下（不送出、留在註冊分頁）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "註冊" }))
    await user.type(screen.getByLabelText("帳號（Email）"), "noname@edms.local")
    await user.click(screen.getByRole("button", { name: "建立帳號" }))
    expect(await screen.findByText("請輸入姓名")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "建立帳號" })).toBeInTheDocument()
  })

  it("忘記密碼 → 送出後顯示統一提示（防列舉）", async () => {
    renderLogin()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "忘記密碼？" }))
    await user.type(screen.getByLabelText("帳號（Email）"), "any@edms.local")
    await user.click(screen.getByRole("button", { name: "送出" }))
    expect(
      await screen.findByText("若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"),
    ).toBeInTheDocument()
  })

  it("重寄驗證信成功回 retry_after → 連結進入冷卻（disabled + 倒數）", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json(
          { error_code: "DP_AUTH_007", error_message: NEUTRAL_MESSAGE },
          { status: 401 },
        ),
      ),
      http.post("/api/resend-verification", () => HttpResponse.json({ message: "已重新寄出", retry_after: 600 })),
    )
    renderLogin()
    const user = userEvent.setup()
    await submitLogin()
    await user.click(await screen.findByRole("button", { name: "重寄驗證信" }))
    // 冷卻中：連結 disabled 且顯示倒數（不斷言確切秒數，避免 tick flaky）
    await waitFor(() => expect(screen.getByRole("button", { name: /重寄驗證信.*後/ })).toBeDisabled())
  })

  it("重寄驗證信遇冷卻 429 → 顯示訊息且連結進入冷卻", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json(
          { error_code: "DP_AUTH_007", error_message: NEUTRAL_MESSAGE },
          { status: 401 },
        ),
      ),
      http.post("/api/resend-verification", () =>
        HttpResponse.json(
          { error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試", retry_after: 300 },
          { status: 429 },
        ),
      ),
    )
    renderLogin()
    const user = userEvent.setup()
    await submitLogin()
    await user.click(await screen.findByRole("button", { name: "重寄驗證信" }))
    expect(await screen.findByText("操作過於頻繁，請稍後再試")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole("button", { name: /重寄驗證信.*後/ })).toBeDisabled())
  })

  it("註冊成功回 retry_after → 「驗證信已寄」的重寄鈕進入冷卻", async () => {
    server.use(
      http.post("/api/register", () => HttpResponse.json({ message: "ok", retry_after: 600 }, { status: 202 })),
    )
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "cooldown@edms.local" })
    expect(await screen.findByText("cooldown@edms.local")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /重寄驗證信.*後/ })).toBeDisabled()
  })

  it("註冊遇 429 → 訊息補「若您並未進行任何操作」的指引（#213）", async () => {
    // 429 對「第一次註冊就被擋」的人完全無指引：他沒操作過任何東西，看不出這是別人觸發的冷卻。
    // #213 已讓「沒寄出信的探測」不再波及他人，但本人在另一裝置註冊過、或有人真的觸發過一次
    // 寄信，都還是會走到這裡。
    server.use(
      http.post("/api/register", () =>
        HttpResponse.json(
          { error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試", retry_after: 600 },
          { status: 429 },
        ),
      ),
    )
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "noidea@edms.local" })

    expect(
      await screen.findByText(/操作過於頻繁，請稍後再試（若您並未進行任何操作，請稍候再試或聯繫系統管理者）/),
    ).toBeInTheDocument()
  })

  it("冷卻綁定 Email：換一個 Email 後「建立帳號」不被前一個 Email 的冷卻誤擋", async () => {
    // 對 aaa 觸發 429 冷卻；換成從未觸發冷卻的 bbb 時，送出鈕應恢復可用（回歸：冷卻須綁定 Email）
    server.use(
      http.post("/api/register", () =>
        HttpResponse.json(
          { error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試", retry_after: 600 },
          { status: 429 },
        ),
      ),
    )
    renderLogin()
    const user = userEvent.setup()
    await fillRegister(user, { email: "aaa@edms.local" })
    await waitFor(() => expect(screen.getByRole("button", { name: /建立帳號.*後/ })).toBeDisabled())

    const emailInput = screen.getByLabelText("帳號（Email）")
    await user.clear(emailInput)
    await user.type(emailInput, "bbb@edms.local")
    expect(screen.getByRole("button", { name: "建立帳號" })).toBeEnabled()
  })
})
