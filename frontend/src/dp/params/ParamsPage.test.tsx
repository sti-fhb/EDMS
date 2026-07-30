import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ParamsPage } from "./ParamsPage"
import { renderWithProviders } from "../../test/renderWithProviders"

/** 點某列（依列內文字定位）右側的「編輯」展開編輯面板。 */
async function openEditByRow(user: UserEvent, rowText: string) {
  const rowEl = screen.getByText(rowText).closest("tr")
  if (!rowEl) throw new Error(`找不到含「${rowText}」的列`)
  await user.click(within(rowEl).getByRole("button", { name: "編輯" }))
}

describe("ParamsPage 系統參數維護流程", () => {
  it("載入後平台頁籤條列 VALUE 參數與影響全平台警告，並有 DM 頁籤", async () => {
    renderWithProviders(<ParamsPage />)

    // 條列：VALUE 明細各一列（顯示中文名 + 目前值）
    expect(await screen.findByText("閒置自動登出（分鐘）")).toBeInTheDocument()
    expect(screen.getByText("15")).toBeInTheDocument()
    expect(screen.getByText(/變更將影響全平台/)).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "平台（共用）" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "文件管理（DM）" })).toBeInTheDocument()
  })

  it("編輯平台參數值 → 先出現影響全平台確認 → 確認後提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.type(field, "10")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 平台級警告確認對話框（PARAMS-005）
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/影響全平台/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "確定儲存" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })

  it("取消平台級警告 → 欄位還原為原值、不儲存", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.type(field, "9")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "取消" }))

    // 還原為原值 15（不因取消而殘留未儲存的 9）
    expect(await screen.findByLabelText("閒置自動登出（分鐘）")).toHaveValue("15")
  })

  it("清空欄位儲存 → 提示請輸入內容、不跳確認", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("請輸入內容")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    // 空值不留白，還原為原值 15
    expect(screen.getByLabelText("閒置自動登出（分鐘）")).toHaveValue("15")
  })

  it("DM 鎖定清單：編輯展開後代碼唯讀、無新增入口", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "文件管理（DM）" }))
    await openEditByRow(user, "文件分類")

    expect(await screen.findByText("SOP")).toBeInTheDocument()
    expect(screen.getByText("代碼鎖定")).toBeInTheDocument()
    // 鎖定清單不提供新增入口
    expect(screen.queryByRole("button", { name: "新增" })).not.toBeInTheDocument()
  })

  it("模組清單編輯展開後新增項目 → 提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await openEditByRow(user, "受訓單位標籤")

    await user.type(screen.getByLabelText("新增代碼"), "DOCTOR")
    await user.type(screen.getByLabelText("新增名稱"), "醫師")
    await user.click(screen.getByRole("button", { name: "新增" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })
})
