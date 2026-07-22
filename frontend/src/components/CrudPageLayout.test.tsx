import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { CrudPageLayout } from "./CrudPageLayout"
import { renderWithProviders } from "../test/renderWithProviders"

describe("CrudPageLayout", () => {
  it("渲染標題與各 slot（篩選 / 操作 / 表格 / 分頁 / 表單）", () => {
    renderWithProviders(
      <CrudPageLayout
        title="使用者管理"
        filterContent={<div>filter-slot</div>}
        actions={<button>actions-slot</button>}
        table={<div>table-slot</div>}
        pagination={<div>pagination-slot</div>}
        form={<div>form-slot</div>}
      />,
    )

    expect(screen.getByRole("heading", { name: "使用者管理" })).toBeInTheDocument()
    expect(screen.getByText("filter-slot")).toBeInTheDocument()
    expect(screen.getByText("actions-slot")).toBeInTheDocument()
    expect(screen.getByText("table-slot")).toBeInTheDocument()
    expect(screen.getByText("pagination-slot")).toBeInTheDocument()
    expect(screen.getByText("form-slot")).toBeInTheDocument()
  })
})
