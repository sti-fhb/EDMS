import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { NAV_GROUPS } from "../layouts/navItems"
import { renderWithProviders } from "../test/renderWithProviders"
import { server } from "../test/server"
import { Sidebar } from "./Sidebar"

describe("Sidebar", () => {
  it("渲染「系統管理者後台」群組標題與其六個導覽項目（無模組門檻、恆顯示）", () => {
    renderWithProviders(<Sidebar />)
    const adminGroup = NAV_GROUPS.find((g) => g.title === "系統管理者後台")
    expect(adminGroup).toBeDefined()
    expect(screen.getByText("系統管理者後台")).toBeInTheDocument()
    expect(adminGroup?.items).toHaveLength(6)
    for (const item of adminGroup?.items ?? []) {
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("具 DM 權限（module-summary dm.has_role=true）時顯示「文件管理」群組與其六個 /dm 項目", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    const dmGroup = NAV_GROUPS.find((g) => g.title === "文件管理")
    expect(dmGroup?.items).toHaveLength(6)
    for (const item of dmGroup?.items ?? []) {
      expect(item.path.startsWith("/dm/")).toBe(true)
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("具 ET 權限時顯示「教育訓練」群組與其四個 /et 項目", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("教育訓練")).toBeInTheDocument())
    const etGroup = NAV_GROUPS.find((g) => g.title === "教育訓練")
    expect(etGroup?.items).toHaveLength(4)
    for (const item of etGroup?.items ?? []) {
      expect(item.path.startsWith("/et/")).toBe(true)
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("無 ET 權限（et.has_role=false）時不顯示「教育訓練」群組（最小知悉）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({ et: { has_role: false }, dm: { has_role: true } }),
      ),
    )
    renderWithProviders(<Sidebar />)
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("教育訓練")).not.toBeInTheDocument())
    expect(screen.queryByText("課程列表")).not.toBeInTheDocument()
  })

  it("無 DM 權限（dm.has_role=false）時不顯示「文件管理」群組（DP 群組仍在）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({ et: { has_role: true }, dm: { has_role: false } }),
      ),
    )
    renderWithProviders(<Sidebar />)
    // DP 群組恆顯示，確認已渲染完成
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
    // 等 module-summary 解析後，DM 群組與其項目皆不應出現
    await waitFor(() => expect(screen.queryByText("文件管理")).not.toBeInTheDocument())
    expect(screen.queryByText("文件庫")).not.toBeInTheDocument()
  })

  it("每個顯示中的導覽項目連到對應路由", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.path)
      }
    }
  })
})