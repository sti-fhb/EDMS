import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ItemList } from "./ItemList"
import type { ItemRow } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const items: ItemRow[] = [
  {
    item_id: 1,
    item_type: "MATERIAL",
    title: "採血示範影片",
    sort_order: 1,
    material_id: 10,
    quiz_id: null,
    version: 0,
    question_count: null,
  },
  {
    item_id: 2,
    item_type: "QUIZ",
    title: "第一章小考",
    sort_order: 2,
    material_id: null,
    quiz_id: 20,
    version: 0,
    question_count: 5,
  },
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

  it("零題的測驗標示警示，教材與有題測驗不標（#410 AC 3）", () => {
    // 🔴 教師端對這件事**完全沒有訊號**：發布檢核只在發布那一刻跑，之後把題目刪光
    // 不擋也不提示。學員則開不起來（0 題測驗回 404），該項目永遠拿不到完成，
    // 整門課因此永遠無法完課——而教師不會知道自己做了這件事。
    //
    // ⚠️ `0` 與 `null` 不可合併：教材的 `question_count` 是 `null`（不是測驗），
    // 合併的話每個教材都會被標成異常。
    renderList({
      items: [
        { item_id: 1, item_type: "MATERIAL", title: "講義", sort_order: 1, material_id: 10, quiz_id: null, version: 0, question_count: null },
        { item_id: 2, item_type: "QUIZ", title: "零題小考", sort_order: 2, material_id: null, quiz_id: 20, version: 0, question_count: 0 },
        { item_id: 3, item_type: "QUIZ", title: "有題小考", sort_order: 3, material_id: null, quiz_id: 21, version: 0, question_count: 3 },
      ],
    })

    expect(screen.getAllByText("尚無題目")).toHaveLength(1)
    // 反向斷言：整列只有一個警示，教材與有題測驗都不能被標到
    expect(screen.getByLabelText("零題小考：尚無題目，學員無法作答")).toBeInTheDocument()
  })

  it("不擋操作——零題測驗照樣點得開、刪得掉（#410 AC 3）", async () => {
    // AC 3 明訂「不擋操作」：教師正要補題目，擋住他等於逼他無法修復。
    const user = userEvent.setup()
    const zero: ItemRow = {
      item_id: 2, item_type: "QUIZ", title: "零題小考", sort_order: 1,
      material_id: null, quiz_id: 20, version: 0, question_count: 0,
    }
    const { onOpen } = renderList({ items: [zero] })

    await user.click(screen.getByText("零題小考"))

    expect(onOpen).toHaveBeenCalledWith(zero)
    expect(screen.getByLabelText("刪除項目 零題小考")).toBeEnabled()
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

  // 原有「新增模式停用新增按鈕並說明原因」一條已移除：#335 起新增模式按下去即自動存
  // 草稿再繼續（`disabled` prop 與那句提示一併刪除），不再有需要解釋的停用狀態。

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
