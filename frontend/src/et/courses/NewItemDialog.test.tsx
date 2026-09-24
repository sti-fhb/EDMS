import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { NewItemDialog } from "./NewItemDialog"
import { ITEM_TITLE_MAX_LEN } from "./itemSchemas"
import type { ItemType } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

function setup(itemType: ItemType | null = "MATERIAL") {
  const onCancel = vi.fn()
  const onConfirm = vi.fn()
  const view = renderWithProviders(
    <NewItemDialog itemType={itemType} submitting={false} onCancel={onCancel} onConfirm={onConfirm} />,
  )
  return { onCancel, onConfirm, view }
}

describe("NewItemDialog：新增項目前先取得名稱（#414）", () => {
  it("itemType 為 null 時什麼都不渲染", () => {
    setup(null)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("依型別顯示教材或測驗的字樣", () => {
    setup("QUIZ")
    expect(screen.getByRole("heading", { name: "新增測驗" })).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "測驗名稱" })).toBeInTheDocument()
  })

  it("不代填預設值——欄位一開始是空的", () => {
    // ⭐ 2026-08-27「不要幫使用者填『新教材』」的判斷仍然成立，本視窗沒有推翻它：
    // 改的是「不代填」的實現方式（先問 vs 留空），不是「要不要代填」。
    setup()
    expect(screen.getByRole("textbox", { name: "教材名稱" })).toHaveValue("")
  })

  it("填了名稱按建立才回報", async () => {
    const { onConfirm } = setup()
    await userEvent.type(screen.getByRole("textbox", { name: "教材名稱" }), "採血流程概論")
    await userEvent.click(screen.getByRole("button", { name: "建立" }))
    expect(onConfirm).toHaveBeenCalledWith("採血流程概論")
  })

  it("名稱前後空白被去除", async () => {
    const { onConfirm } = setup()
    await userEvent.type(screen.getByRole("textbox", { name: "教材名稱" }), "  採血流程  ")
    await userEvent.click(screen.getByRole("button", { name: "建立" }))
    expect(onConfirm).toHaveBeenCalledWith("採血流程")
  })

  it("空白名稱擋下並提示，不回報", async () => {
    const { onConfirm } = setup()
    await userEvent.click(screen.getByRole("button", { name: "建立" }))
    expect(await screen.findByText("請輸入名稱")).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("全空白等同留空，同樣擋下", async () => {
    // `min-length` 擋不掉「   」——它有長度。與後端 `_strip_title` 同一判準。
    const { onConfirm } = setup()
    await userEvent.type(screen.getByRole("textbox", { name: "教材名稱" }), "   ")
    await userEvent.click(screen.getByRole("button", { name: "建立" }))
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("按 Enter 等同按建立", async () => {
    const { onConfirm } = setup()
    await userEvent.type(screen.getByRole("textbox", { name: "教材名稱" }), "採血流程{Enter}")
    expect(onConfirm).toHaveBeenCalledWith("採血流程")
  })

  it("送出中時 Enter 不再重複送出（#414 security review LOW-1）", async () => {
    // 🔴 `submitting` 只 disable 了「建立」按鈕，而鍵盤 auto-repeat 會在長按時連發
    // keydown。少了 `submit` 開頭那行守衛，長按 Enter 會送出 N 次建立請求、建出一排
    // 重複項目——而該端點沒有掛限流。
    const onConfirm = vi.fn()
    renderWithProviders(
      <NewItemDialog itemType="MATERIAL" submitting onCancel={vi.fn()} onConfirm={onConfirm} />,
    )
    const field = screen.getByRole("textbox", { name: "教材名稱" })
    await userEvent.type(field, "採血流程")
    await userEvent.type(field, "{Enter}{Enter}{Enter}")

    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("取消不回報任何名稱", async () => {
    // 🔴 本 issue 的核心：取消時 DB 裡什麼都沒有，不需要任何清理。
    // 舊行為是按下「新增項目」當下就建了空殼，清理只掛在取消上。
    const { onCancel, onConfirm } = setup()
    await userEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("輸入長度受上限約束", () => {
    setup()
    expect(screen.getByRole("textbox", { name: "教材名稱" })).toHaveAttribute(
      "maxlength",
      String(ITEM_TITLE_MAX_LEN),
    )
  })
})
