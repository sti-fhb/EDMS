import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ParamsPage } from "./ParamsPage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("ParamsPage 系統參數維護流程", () => {
  it("載入後平台頁籤顯示 VALUE 參數與影響全平台警告，並有 DM 頁籤", async () => {
    renderWithProviders(<ParamsPage />)

    expect(await screen.findByText("JWT 設定")).toBeInTheDocument()
    expect(screen.getByLabelText("閒置自動登出（分鐘）")).toBeInTheDocument()
    expect(screen.getByText(/變更將影響全平台/)).toBeInTheDocument()
    // 分頁籤：平台 + DM（皆有資料）
    expect(screen.getByRole("tab", { name: "平台（共用）" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "文件管理（DM）" })).toBeInTheDocument()
  })

  it("編輯平台參數值 → 先出現影響全平台確認 → 確認後提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")

    await user.clear(field)
    await user.type(field, "10")
    await user.click(screen.getAllByRole("button", { name: "儲存" })[0])

    // 平台級警告確認對話框（PARAMS-005）
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/影響全平台/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "確定儲存" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })

  it("取消平台級警告 → 欄位還原為原值、不儲存", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")

    await user.clear(field)
    await user.type(field, "9")
    await user.click(screen.getAllByRole("button", { name: "儲存" })[0])

    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "取消" }))

    // 還原為原值 15（不因取消而殘留未儲存的 9）
    expect(screen.getByLabelText("閒置自動登出（分鐘）")).toHaveValue("15")
  })

  it("清空欄位儲存 → 提示請輸入內容、不跳確認", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")

    await user.clear(field)
    await user.click(screen.getAllByRole("button", { name: "儲存" })[0])

    expect(await screen.findByText("請輸入內容")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("DM 鎖定清單：代碼唯讀、無新增入口", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("JWT 設定")

    await user.click(screen.getByRole("tab", { name: "文件管理（DM）" }))

    expect(await screen.findByText("文件分類")).toBeInTheDocument()
    expect(screen.getByText("SOP")).toBeInTheDocument()
    expect(screen.getByText("代碼鎖定")).toBeInTheDocument()
    // 鎖定清單不提供新增入口
    expect(screen.queryByRole("button", { name: "新增" })).not.toBeInTheDocument()
  })

  it("模組清單新增項目 → 提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("JWT 設定")

    // 清單維護在模組頁籤（平台頁籤僅 VALUE 參數，不含系統 enum）
    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await screen.findByText("受訓單位標籤")
    await user.type(screen.getByLabelText("新增代碼"), "DOCTOR")
    await user.type(screen.getByLabelText("新增名稱"), "醫師")
    await user.click(screen.getByRole("button", { name: "新增" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })
})
