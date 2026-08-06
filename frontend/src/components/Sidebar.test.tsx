import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { NAV_GROUPS } from "../layouts/navItems"
import { muiTheme } from "../styles/muiTheme"
import { Sidebar } from "./Sidebar"

function renderSidebar() {
  return render(
    <ThemeProvider theme={muiTheme}>
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe("Sidebar", () => {
  it("渲染「系統管理者後台」群組標題與其六個導覽項目", () => {
    renderSidebar()
    const adminGroup = NAV_GROUPS.find((g) => g.title === "系統管理者後台")
    expect(adminGroup).toBeDefined()
    expect(screen.getByText("系統管理者後台")).toBeInTheDocument()
    expect(adminGroup?.items).toHaveLength(6)
    for (const item of adminGroup?.items ?? []) {
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("每個導覽項目連到對應 /dp 路由", () => {
    renderSidebar()
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.path)
      }
    }
  })
})
