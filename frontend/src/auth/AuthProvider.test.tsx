import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http as msw, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "./AuthProvider"
import { LoginOverlay } from "./LoginOverlay"
import { useAuth } from "./useAuth"
import { http } from "../services/http"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

/**
 * 自動登出行為（#741）。
 *
 * 原本只有「收到 401 才登出」，兩個手冊寫了、程式沒做的情境因此從未發生：
 * 閒置到期時使用者不動 ⇒ 不會有請求 ⇒ 畫面一直停著；使用中被停用 / 鎖定時後端回的是
 * **403**，各作業只跳錯誤訊息，要等 token 自然過期才回登入頁、而且提示的是「閒置逾時」。
 *
 * ⚠️ 文案斷言刻意寫**完整句子**而非關鍵字：停用 / 鎖定兩句逐字沿用登入時後端回的
 * `error_message`，寫關鍵字的話後端改字時這裡不會紅。
 */

/** MSW 預設登入回應的 `expires_in`（秒），與 `test/server.ts` 同步。 */
const EXPIRES_IN_SEC = 900
/** `AuthProvider` 的到期檢查間隔（毫秒）；推進時間要蓋過它才看得到登出。 */
const EXPIRY_CHECK_MS = 15 * 1000

function Harness() {
  const { isAuthenticated, sessionEndedReason } = useAuth()
  return (
    <>
      <div data-testid="status">{isAuthenticated ? "authed" : "anon"}</div>
      <div data-testid="reason">{sessionEndedReason ?? "none"}</div>
      {!isAuthenticated && <LoginOverlay />}
    </>
  )
}

function renderAuth() {
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

async function login(user = userEvent.setup()) {
  await user.type(screen.getByLabelText("帳號（Email）"), "u@edms.local")
  await user.type(screen.getByLabelText("密碼"), "Abcd1234")
  await user.click(screen.getByRole("button", { name: "登入" }))
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authed"))
}

/** 讓下一次請求回指定的 403；回傳那次請求的 promise（必須真的失敗，見各測試的正向錨點）。 */
function respond403(errorCode: string, errorMessage: string) {
  server.use(
    msw.get("/api/dp/user/me", () =>
      HttpResponse.json({ error_code: errorCode, error_message: errorMessage }, { status: 403 }),
    ),
  )
  return http.get("/dp/user/me") //  的 baseURL 已是 /api，這裡不可重複帶
}

afterEach(() => {
  vi.useRealTimers()
})

describe("AuthProvider 自動登出", () => {
  it("登入後完全不操作，到期時自動回到登入畫面並提示閒置逾時", async () => {
    // 🔴 假時鐘必須裝在 render **之前**：到期檢查的 `setInterval` 是 `AuthProvider` 掛載時
    // 建立的，裝在那之後 `advanceTimersByTime` 控制不到它——會得到「推進了 15 分鐘卻
    // 什麼都沒發生」，看起來像功能沒做，實際是測試沒接上。
    // ⚠️ `toFake` 只列需要的三個。預設會連 `setTimeout` 一起假造，而 MSW / axios 內部靠它
    // 完成請求 —— 那會讓登入永遠等不到回應，症狀是 `Test timed out in 5000ms`，
    // 看起來像測試寫錯，實際是把不該凍的東西凍住了。
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] })
    renderAuth()
    await login()

    // 登入後**不再有任何操作**：`AuthProvider` 以 mousedown / keydown 記錄「活躍中」，
    // 這裡若再點任何東西，換發計時器就會把到期時間往後推、測不到到期。
    await act(async () => {
      vi.advanceTimersByTime(EXPIRES_IN_SEC * 1000 + EXPIRY_CHECK_MS)
    })

    expect(screen.getByTestId("status")).toHaveTextContent("anon")
    expect(screen.getByTestId("reason")).toHaveTextContent("IDLE")
    expect(screen.getByText("閒置逾時已自動登出，請重新登入")).toBeInTheDocument()
  })

  it("使用中被管理者停用（403 DP_AUTH_004）→ 下一次請求即回登入畫面並提示已停用", async () => {
    renderAuth()
    await login()

    await expect(respond403("DP_AUTH_004", "帳號已停用，請洽管理者")).rejects.toThrow()

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anon"))
    expect(screen.getByTestId("reason")).toHaveTextContent("DISABLED")
    expect(screen.getByText("帳號已停用，請洽管理者")).toBeInTheDocument()
  })

  it("使用中被鎖定（403 DP_AUTH_005）→ 同上，提示已鎖定", async () => {
    renderAuth()
    await login()

    await expect(respond403("DP_AUTH_005", "帳號已鎖定，請洽管理者或稍後再試")).rejects.toThrow()

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anon"))
    expect(screen.getByTestId("reason")).toHaveTextContent("LOCKED")
    expect(screen.getByText("帳號已鎖定，請洽管理者或稍後再試")).toBeInTheDocument()
  })

  it("⛔ 其他 403（權限不足）不得登出", async () => {
    renderAuth()
    await login()

    // 正向錨點：這個請求**確實**以 403 失敗了。少了它，下方「仍在登入中」會因為
    // 「根本沒發生 403」而恆真——那是這條測試唯一會假綠的方式。
    await expect(respond403("DP_AUTH_006", "需要模組管理者權限")).rejects.toThrow()

    expect(screen.getByTestId("status")).toHaveTextContent("authed")
    expect(screen.getByTestId("reason")).toHaveTextContent("none")
  })
})
