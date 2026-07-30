import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { RouterProvider, createMemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AppShell } from "./AppShell"
import { RootLayout } from "./RootLayout"
import { AuthProvider } from "../auth/AuthProvider"
import { WelcomePage } from "../home/WelcomePage"
import { muiTheme } from "../styles/muiTheme"

const HEADER_TITLE = "EDMS 教育訓練文件管理系統"

/**
 * 以真實 AuthProvider + memory router 渲染「RootLayout → AppShell → WelcomePage」，
 * 貼近正式 provider 疊法（見 main.tsx）。不 mock service，登入 / 登出 / getMe / version 走 MSW。
 */
function renderApp() {
  const router = createMemoryRouter(
    [
      {
        element: <RootLayout />,
        children: [
          {
            element: <AppShell />,
            children: [{ index: true, element: <WelcomePage /> }],
          },
        ],
      },
    ],
    { initialEntries: ["/"] },
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

async function login(user: UserEvent) {
  await user.type(screen.getByLabelText("帳號（Email）"), "u@edms.local")
  await user.type(screen.getByLabelText("密碼"), "Abcd1234")
  await user.click(screen.getByRole("button", { name: "登入" }))
}

describe("AppShell 統一導覽殼", () => {
  it("登入後：全域頂列 + 常駐側欄（後台群組）+ 中性歡迎頁", async () => {
    const user = userEvent.setup()
    renderApp()
    await login(user)
    // 全域頂列品牌
    expect(await screen.findByText(HEADER_TITLE)).toBeInTheDocument()
    // 中性歡迎頁：問候帶姓名（MSW /me = 測試員）+ 系統定位
    expect(await screen.findByText("歡迎，測試員")).toBeInTheDocument()
    expect(screen.getByText("教育訓練與文件管理系統")).toBeInTheDocument()
    // 側欄常駐（與舊入口頁「無側欄」相反）：後台群組 + Drawer 存在
    expect(screen.getByText("系統管理者後台")).toBeInTheDocument()
    expect(document.querySelector(".MuiDrawer-root")).not.toBeNull()
  })

  it("點登出 → 清狀態、回登入頁", async () => {
    const user = userEvent.setup()
    renderApp()
    await login(user)
    await screen.findByText(HEADER_TITLE)
    // 已登入：登入表單已撤除
    expect(screen.queryByLabelText("帳號（Email）")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "個資選單" }))
    await user.click(screen.getByRole("menuitem", { name: "登出" }))
    // 登出後 LoginOverlay 重現（回登入頁）
    await waitFor(() => expect(screen.getByLabelText("帳號（Email）")).toBeInTheDocument())
  })

  it("點三條線 icon → 收合 / 展開側欄", async () => {
    const user = userEvent.setup()
    renderApp()
    await login(user)
    await screen.findByText(HEADER_TITLE)
    expect(screen.getByText("系統管理者後台")).toBeInTheDocument()

    // 收合：側欄不再渲染
    await user.click(screen.getByRole("button", { name: "切換側欄" }))
    await waitFor(() => expect(screen.queryByText("系統管理者後台")).not.toBeInTheDocument())

    // 再展開：側欄回來
    await user.click(screen.getByRole("button", { name: "切換側欄" }))
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
  })
})
