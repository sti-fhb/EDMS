import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { DmPersonalPage } from "./DmPersonalPage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("DmPersonalPage 個人專區（DM07）", () => {
  it("我的文件動態：撰寫者 / 審核者視角事件；送審中可撤回", async () => {
    renderWithProviders(<DmPersonalPage />)
    expect(await screen.findByText("待審文件 A")).toBeInTheDocument() // 撰寫者視角（送審中）
    expect(screen.getByText("我要審的文件")).toBeInTheDocument() // 審核者視角（待處理）
    expect(screen.getByText("撰寫者視角（近 30 天）")).toBeInTheDocument()
    expect(screen.getByText("審核者視角（近 30 天）")).toBeInTheDocument()
    // 送審中 → 有撤回送審鈕
    expect(screen.getByRole("button", { name: "撤回送審" })).toBeInTheDocument()
  })

  it("撤回送審 → 二次確認 → 成功 toast（DM-MSG-DM07-005）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("button", { name: "撤回送審" }))
    expect(await screen.findByText("確定撤回送審？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認撤回" }))
    expect(await screen.findByText("已撤回送審，已通知原指派審核者")).toBeInTheDocument()
  })

  it("草稿匣：三類標記 + 繼續編輯 / 刪除", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    expect(await screen.findByText("領血 SOP 草稿")).toBeInTheDocument()
    expect(screen.getByText("被退回待修改")).toBeInTheDocument() // rejected 類
    expect(screen.getByText("未送審")).toBeInTheDocument() // unsubmitted 類
    expect(screen.getAllByRole("button", { name: "繼續編輯" }).length).toBeGreaterThanOrEqual(2)
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
