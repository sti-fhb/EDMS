import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ItemList } from "./ItemList"
import type { ItemRow } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const items: ItemRow[] = [
  { item_id: 1, item_type: "MATERIAL", title: "採血示範影片", sort_order: 1, material_id: 10, quiz_id: null, version: 0 },
  { item_id: 2, item_type: "QUIZ", title: "第一章小考", sort_order: 2, material_id: null, quiz_id: 20, version: 0 },
]

function renderList(overrides: Partial<Parameters<typeof ItemList>[0]> = {}) {
  const handlers = {
    onAdd: vi.fn(),
    onOpen: vi.fn(),
    onDelete: vi.fn(),
    onReorder: vi.fn(),
  }
  renderWithProviders(<ItemList items={items} readOnly={false} {...handlers} {...overrides} />)
  return handlers
}

describe("章節項目清單", () => {
  it("列出項目與其類型標記", () => {
    renderList()
    expect(screen.getByText("採血示範影片")).toBeInTheDocument()
    expect(screen.getByText("第一章小考")).toBeInTheDocument()
    expect(screen.getByText("教材")).toBeInTheDocument()
    expect(screen.getByText("測驗")).toBeInTheDocument()
  })

  it("點項目名稱時開啟對應視窗", async () => {
    const user = userEvent.setup()
    const { onOpen } = renderList()
    await user.click(screen.getByText("採血示範影片"))
    expect(onOpen).toHaveBeenCalledWith(items[0])
  })

  it("新增項目選單提供教材與測驗兩種", async () => {
    const user = userEvent.setup()
    const { onAdd } = renderList()
    await user.click(screen.getByRole("button", { name: "新增項目" }))

    expect(await screen.findByRole("menuitem", { name: /教材/ })).toBeInTheDocument()
    await user.click(screen.getByRole("menuitem", { name: /測驗/ }))
    expect(onAdd).toHaveBeenCalledWith("QUIZ")
  })

  it("刪除項目時通知呼叫端", async () => {
    const user = userEvent.setup()
    const { onDelete } = renderList()
    await user.click(screen.getByRole("button", { name: "刪除項目 第一章小考" }))
    expect(onDelete).toHaveBeenCalledWith(items[1])
  })

  it("唯讀模式不顯示新增 / 刪除 / 拖拉手把", () => {
    renderList({ readOnly: true })
    expect(screen.queryByRole("button", { name: "新增項目" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /刪除項目/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/拖曳調整/)).not.toBeInTheDocument()
    // 仍可點開檢視
    expect(screen.getByText("採血示範影片")).toBeInTheDocument()
  })

  it("新增模式停用新增按鈕並說明原因", () => {
    renderList({ items: [], disabled: true })
    expect(screen.getByRole("button", { name: "新增項目" })).toBeDisabled()
    expect(screen.getByText("請先儲存草稿後再新增項目")).toBeInTheDocument()
  })

  it("空清單顯示引導文字", () => {
    renderList({ items: [] })
    expect(screen.getByText(/尚無項目/)).toBeInTheDocument()
  })

  it("items 未提供時降級為空清單而非崩潰", () => {
    // 後端恆回此欄位，但少一個欄位不該讓整個課程編輯頁變成白畫面
    renderList({ items: undefined })
    expect(screen.getByText(/尚無項目/)).toBeInTheDocument()
  })
})
