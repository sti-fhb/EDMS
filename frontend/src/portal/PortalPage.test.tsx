import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { PortalPage } from "./PortalPage"
import { server } from "../test/server"
import { muiTheme } from "../styles/muiTheme"

function renderPortal(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>{ui}</ThemeProvider>
    </QueryClientProvider>,
  )
}

describe("PortalPage", () => {
  it("無 DM 角色 → DM 卡呈未開通、ET 卡可進入", async () => {
    renderPortal(<PortalPage />)
    expect(await screen.findByText("教育訓練（ET）")).toBeInTheDocument()
    expect(screen.getByText("🔒 未開通")).toBeInTheDocument()
  })

  it("具 DM 角色 → DM 卡可進入（無未開通標記）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({ et: { has_role: true }, dm: { has_role: true } }),
      ),
    )
    renderPortal(<PortalPage />)
    expect(await screen.findByText("文件管理（DM）")).toBeInTheDocument()
    expect(screen.queryByText("🔒 未開通")).not.toBeInTheDocument()
    // ET + DM 兩張卡皆可進入
    expect(screen.getAllByRole("link", { name: "進入" })).toHaveLength(2)
  })

  it("顯示歡迎橫幅", async () => {
    renderPortal(<PortalPage />)
    expect(await screen.findByText("歡迎使用 EDMS 教育訓練文件管理系統")).toBeInTheDocument()
  })
})
