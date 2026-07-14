import { ThemeProvider } from "@mui/material/styles"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { DP_NAV_ITEMS } from "../layouts/navItems"
import { muiTheme } from "../styles/muiTheme"
import { Sidebar } from "./Sidebar"

describe("Sidebar", () => {
  it("渲染 DP 後台六個導覽項目並對齊 wireframe 畫面", () => {
    render(
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </ThemeProvider>,
    )

    expect(DP_NAV_ITEMS).toHaveLength(6)
    for (const item of DP_NAV_ITEMS) {
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("每個導覽項目連到對應 /dp 路由", () => {
    render(
      <ThemeProvider theme={muiTheme}>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </ThemeProvider>,
    )

    for (const item of DP_NAV_ITEMS) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.path)
    }
  })
})
