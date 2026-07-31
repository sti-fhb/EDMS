import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { SchedulePage } from "./SchedulePage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("SchedulePage 排程作業總覽（唯讀）", () => {
  it("列出排程 job（含 cron / 啟停 / 上次結果）", async () => {
    renderWithProviders(<SchedulePage />)

    expect(await screen.findByText(/SCHDP001/)).toBeInTheDocument()
    expect(screen.getByText("0 8 * * *")).toBeInTheDocument()
    expect(screen.getByText("啟用")).toBeInTheDocument()
    expect(screen.getByText("停用")).toBeInTheDocument() // ET 預留列
    expect(screen.getByText("SUCCESS")).toBeInTheDocument()
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

    // 點 ET 預留列（無歷程）的歷程鈕
    await user.click(screen.getAllByRole("button", { name: "執行歷程" })[1])

    expect(await screen.findByText("尚無排程執行紀錄")).toBeInTheDocument()
  })

  it("介面無啟停 / 補跑 / 新增 / 編輯 / 刪除任何操作按鈕（唯讀）", async () => {
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    expect(
      screen.queryByRole("button", { name: /啟用中|停用中|啟動|停止|補跑|重跑|新增|建立|編輯|刪除/ }),
    ).not.toBeInTheDocument()
  })
})
