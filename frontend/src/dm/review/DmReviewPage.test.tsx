import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { DmReviewPage } from "./DmReviewPage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("DmReviewPage 簽核中心（DM04）", () => {
  it("待簽核清單：列出指派項目、停留逾門檻標紅警示", async () => {
    renderWithProviders(<DmReviewPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    // 停留 12 天（≥ 7）→ 標紅 ⚠
    expect(screen.getByText(/12 天 ⚠/)).toBeInTheDocument()
    expect(screen.getByText(/1 天/)).toBeInTheDocument()
  })

  it("點列展開明細：變更摘要 + 新舊版下載 + 核准/退回入口", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    expect(await screen.findByText(/簽核明細 —/)).toBeInTheDocument()
    expect(screen.getByText(/補充第 5 點異常通報流程/)).toBeInTheDocument()
    // 新舊版下載列
    expect(screen.getByText("待審版本")).toBeInTheDocument()
    expect(screen.getByText("目前發布版")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "核准並發布" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "退回" })).toBeInTheDocument()
  })

  it("核准並發布 → 二次確認 → 成功 toast（DM-MSG-DM04-001）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    // 二次確認 dialog
    expect(await screen.findByText("確定核准此項目？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認核准" }))
    expect(await screen.findByText("已核准並發布，已通知撰寫者")).toBeInTheDocument()
  }, 20000)

  it("退回：空原因擋（-004）、填原因後成功 toast（-005）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "退回" }))
    // 空原因 → 擋
    await user.click(await screen.findByRole("button", { name: "確認退回" }))
    expect(await screen.findByText("請填寫退回原因")).toBeInTheDocument()
    // 填原因 → 成功
    await user.type(screen.getByLabelText(/退回原因/), "需補充異常通報")
    await user.click(screen.getByRole("button", { name: "確認退回" }))
    expect(await screen.findByText("已退回並通知撰寫者")).toBeInTheDocument()
  }, 20000)

  it("已完成頁籤：呈現過往處理結果（唯讀）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByRole("tab", { name: /已完成/ }))
    expect(await screen.findByText("舊案 SOP")).toBeInTheDocument()
    expect(screen.getByText("已核准")).toBeInTheDocument()
    // AC8 搜尋分頁：提供文件名搜尋框
    expect(screen.getByLabelText(/搜尋文件名稱/)).toBeInTheDocument()
  })
})
