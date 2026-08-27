import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { DmPersonalPage } from "./DmPersonalPage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("DmPersonalPage 個人專區（DM07）", () => {
  it("我的文件動態：撰寫者 / 審核者視角事件；送審中可撤回；逾門檻顯催辦中（AC5）", async () => {
    renderWithProviders(<DmPersonalPage />)
    expect(await screen.findByText("待審文件 A")).toBeInTheDocument() // 撰寫者視角（送審中）
    expect(screen.getByText("我逾期要審的文件")).toBeInTheDocument() // 審核者視角
    expect(screen.getByText("撰寫者視角（近 30 天）")).toBeInTheDocument()
    expect(screen.getByText("審核者視角（近 30 天）")).toBeInTheDocument()
    // 送審中 → 有撤回送審鈕
    expect(screen.getByRole("button", { name: "撤回送審" })).toBeInTheDocument()
    // 審核者視角逾催辦門檻 → 顯示「催辦中」（is_overdue=true）
    expect(screen.getByText("催辦中")).toBeInTheDocument()
    // 待處理 / 催辦中 → 有「前往簽核中心」button
    expect(screen.getByRole("button", { name: "前往簽核中心" })).toBeInTheDocument()
    // 狀態變動歷程：同一送審週期展開為 送審 + 退回 兩列（#5）
    expect(screen.getAllByText("被退回文件 B")).toHaveLength(2)
    expect(screen.getAllByText("已退回").length).toBeGreaterThanOrEqual(1) // resolved 事件（撰寫者/審核者皆有）
    // 對造人欄（指定審核者 / 送審者）中文姓名
    expect(screen.getByText("送審者")).toBeInTheDocument() // 審核者視角表頭
    expect(screen.getAllByText("陳送審").length).toBeGreaterThanOrEqual(1)
    // 審核者視角已完成項也展開為兩列（Round-4 item 2）：送審 + 已退回
    expect(screen.getAllByText("我已退回的文件 D")).toHaveLength(2)
    // 標籤一律中文、不再出現「收到送審」
    expect(screen.queryByText("收到送審")).not.toBeInTheDocument()
  })

  it("撤回送審 → 二次確認 → 成功 toast（DM-MSG-DM07-005）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("button", { name: "撤回送審" }))
    expect(await screen.findByText("確定撤回送審？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認撤回" }))
    expect(await screen.findByText("已撤回送審，已通知原指派審核者")).toBeInTheDocument()
  })

  it("草稿匣：三類標記 + 繼續編輯 / 刪除；已廢止孤兒草稿仍顯示但續編灰化", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    expect(await screen.findByText("領血 SOP 草稿")).toBeInTheDocument()
    expect(screen.getByText("被退回待修改")).toBeInTheDocument() // rejected 類
    expect(screen.getAllByText("未送審").length).toBeGreaterThanOrEqual(1) // unsubmitted 類
    // 已廢止孤兒草稿仍留在草稿匣（不隱藏）
    expect(screen.getByText("已廢止孤兒草稿")).toBeInTheDocument()
    // 三筆皆有「繼續編輯」；已廢止那筆為 disabled、其餘可按
    const editButtons = screen.getAllByRole("button", { name: "繼續編輯" })
    expect(editButtons).toHaveLength(3)
    expect(editButtons.filter((b) => (b as HTMLButtonElement).disabled)).toHaveLength(1)
    // 已廢止列可刪除（讓使用者自行清掉）
    expect(screen.getAllByRole("button", { name: "刪除" })).toHaveLength(3)
  })

  it("刪除草稿 → 確認（DM-MSG-DM07-004）→ 成功 toast", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    await screen.findByText("領血 SOP 草稿")
    await user.click(screen.getAllByRole("button", { name: "刪除" })[0])
    expect(await screen.findByText("確定刪除此草稿？刪除後不可復原")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認刪除" }))
    expect(await screen.findByText("草稿已刪除")).toBeInTheDocument()
  })

  it("動態載入失敗 → 顯示錯誤", async () => {
    const { server } = await import("../../test/server")
    const { http, HttpResponse } = await import("msw")
    server.use(http.get("/api/dm/personal/activity", () => HttpResponse.json({ detail: "err" }, { status: 500 })))
    renderWithProviders(<DmPersonalPage />)
    expect(await screen.findByText(/載入動態失敗/)).toBeInTheDocument()
  })
})
