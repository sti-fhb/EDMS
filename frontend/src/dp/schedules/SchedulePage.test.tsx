import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { SchedulePage } from "./SchedulePage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("SchedulePage 排程作業總覽（可編輯）", () => {
  it("列出排程 job（cron / 狀態 / 最近執行 / 下次執行）", async () => {
    renderWithProviders(<SchedulePage />)

    expect(await screen.findByText(/SCHDP001/)).toBeInTheDocument()
    expect(screen.getByText("0 8 * * *")).toBeInTheDocument()
    // 欄位標題：狀態（原「啟停」）、下次執行；無「結果」欄
    expect(screen.getByRole("columnheader", { name: "狀態" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "下次執行" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "結果" })).not.toBeInTheDocument()
    expect(screen.getByText("啟用")).toBeInTheDocument()
    expect(screen.getByText("停用")).toBeInTheDocument() // ET 預留列
  })

  it("點歷程 → 開 Dialog 顯示執行歷程", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    await user.click(screen.getAllByRole("button", { name: "執行歷程" })[0])

    expect(await screen.findByText(/執行歷程/)).toBeInTheDocument()
    expect(screen.getByText("錯誤 / 跳過原因")).toBeInTheDocument()
  })

  it("無歷程之 job → 空狀態 SCHEDULE-001", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHET001/)

    await user.click(screen.getAllByRole("button", { name: "執行歷程" })[1])

    expect(await screen.findByText("尚無排程執行紀錄")).toBeInTheDocument()
  })

  it("點編輯 → 開 Dialog（JOB_ID 唯讀）→ 改名/cron/啟停儲存 → 成功提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    await user.click(screen.getAllByRole("button", { name: "編輯" })[0])
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByLabelText("Job ID")).toBeDisabled()

    const name = within(dialog).getByLabelText(/作業名稱/)
    await user.clear(name)
    await user.type(name, "平台每日作業（改）")
    await user.click(within(dialog).getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("排程已更新")).toBeInTheDocument()
  })

  it("無手動補跑按鈕（補跑不開放）", async () => {
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    expect(
      screen.queryByRole("button", { name: /補跑|重跑|手動執行|立即執行/ }),
    ).not.toBeInTheDocument()
  })
})