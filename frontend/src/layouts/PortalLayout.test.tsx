import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { RouterProvider, createMemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { PortalLayout } from "./PortalLayout"
import { RootLayout } from "./RootLayout"
import { AuthProvider } from "../auth/AuthProvider"
import { PortalPage } from "../portal/PortalPage"
import { muiTheme } from "../styles/muiTheme"

const HEADER_TITLE = "EDMS 教育訓練文件管理系統"

/**
 * 以真實 AuthProvider + memory router 渲染「RootLayout → PortalLayout → PortalPage」，
 * 貼近正式 provider 疊法（見 main.tsx）。不 mock service，登入 / 登出走 MSW（test/server.ts）。
 */
function renderApp() {
  const router = createMemoryRouter(
    [
      {
        element: <RootLayout />,
        children: [
          {
            path: "portal",
            element: <PortalLayout />,
            children: [{ index: true, element: <PortalPage /> }],
          },
        ],
      },
    ],
    { initialEntries: ["/portal"] },
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

describe("PortalLayout", () => {
  it("登入後入口頁：顯示全域頂列與登出、模組卡片，且無側欄", async () => {
    const user = userEvent.setup()
    renderApp()
    await login(user)
    // 全域頂列（對齊 wireframe brand）與入口頁內容
    expect(await screen.findByText(HEADER_TITLE)).toBeInTheDocument()
    expect(await screen.findByText("教育訓練（ET）")).toBeInTheDocument()
    // 頂列右上個資選單內含登出
    await user.click(screen.getByRole("button", { name: "個資選單" }))
    expect(screen.getByRole("menuitem", { name: "登出" })).toBeInTheDocument()
    // 入口頁無左側側欄（僅頂列 + 卡片），對齊 wireframe
    expect(document.querySelector(".MuiDrawer-root")).toBeNull()
  })

  it("入口頁點登出 → 清狀態、回到登入頁", async () => {
    const user = userEvent.setup()
    renderApp()
    await login(user)
    await screen.findByText(HEADER_TITLE)
    // 已登入：登入表單已撤除
    expect(screen.queryByLabelText("帳號（Email）")).not.toBeInTheDocument()
    // 開個資選單 → 登出
    await user.click(screen.getByRole("button", { name: "個資選單" }))
    await user.click(screen.getByRole("menuitem", { name: "登出" }))
    // 登出後 LoginOverlay 重現（回登入頁）
    await waitFor(() => expect(screen.getByLabelText("帳號（Email）")).toBeInTheDocument())
  })
})