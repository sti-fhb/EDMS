import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AppTable } from "./AppTable"
import type { AppColumn } from "./AppTable"
import { renderWithProviders } from "../test/renderWithProviders"

interface Row {
  id: string
  name: string
  age: number
}

const columns: AppColumn<Row>[] = [
  { key: "name", title: "姓名", dataIndex: "name" },
  { key: "age", title: "年齡", dataIndex: "age" },
  { key: "actions", title: "操作", render: (_v, r) => <span>編輯-{r.name}</span> },
]

const rows: Row[] = [
  { id: "1", name: "陳大華", age: 30 },
  { id: "2", name: "王曉明", age: 25 },
]

describe("AppTable", () => {
  it("渲染欄位標題與資料列（含自訂 render）", () => {
    renderWithProviders(<AppTable columns={columns} data={rows} rowKey="id" />)

    expect(screen.getByText("姓名")).toBeInTheDocument()
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    expect(screen.getByText("25")).toBeInTheDocument()
    expect(screen.getByText("編輯-王曉明")).toBeInTheDocument()
  })

  it("loading 時顯示轉圈、不顯示資料", () => {
    renderWithProviders(<AppTable columns={columns} data={[]} rowKey="id" loading />)

    expect(screen.getByRole("progressbar")).toBeInTheDocument()
  })

  it("無資料時顯示 emptyText", () => {
    renderWithProviders(<AppTable columns={columns} data={[]} rowKey="id" emptyText="查無使用者" />)

    expect(screen.getByText("查無使用者")).toBeInTheDocument()
  })
})
