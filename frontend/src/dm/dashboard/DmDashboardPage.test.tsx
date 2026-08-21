import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { DmDashboardPage } from "./DmDashboardPage"
import { server } from "../../test/server"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("DmDashboardPage 系統儀表板（DM00）", () => {
  it("統計卡：4 內建分類數量 + 總計", async () => {
    renderWithProviders(<DmDashboardPage />)
    expect(await screen.findByText("SOP")).toBeInTheDocument()
    expect(screen.getByText("系統操作手冊")).toBeInTheDocument()
    expect(screen.getByText("訓練教材")).toBeInTheDocument()
    expect(screen.getByText("其他")).toBeInTheDocument()
    expect(screen.getByText("42")).toBeInTheDocument()
    // 總計
    expect(screen.getByText(/總計/)).toBeInTheDocument()
    expect(screen.getByText("76")).toBeInTheDocument()
  })

  it("最新更新公告：列出近 30 天發布 + 新增/新版本 badge", async () => {
    renderWithProviders(<DmDashboardPage />)
    expect(await screen.findByText("用血回報訓練教材")).toBeInTheDocument()
    expect(screen.getByText("領血確認標準作業程序")).toBeInTheDocument()
    expect(screen.getByText(/新增 1\.0/)).toBeInTheDocument()
    expect(screen.getByText(/新版本 2\.1/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /查看全部文件/ })).toBeInTheDocument()
  })

  it("點公告列進入詳細頁（可點、不報錯）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmDashboardPage />)
    const row = (await screen.findByText("用血回報訓練教材")).closest("[role=button]") as HTMLElement
    await user.click(row)
    // 導向由 router 處理；此處驗證點擊未拋錯、列仍為可點 button
    expect(row).toBeInTheDocument()
  })

  it("公告空狀態：近 30 天無事件顯示提示（DM-MSG-DM00-001）", async () => {
    server.use(http.get("/api/dm/dashboard/announcements", () => HttpResponse.json([])))
    renderWithProviders(<DmDashboardPage />)
    // 統計卡照常載入
    expect(await screen.findByText("SOP")).toBeInTheDocument()
    expect(await screen.findByText("近期無新發布文件")).toBeInTheDocument()
  })

  it("統計全 0：卡片仍顯示、總計 0", async () => {
    server.use(
      http.get("/api/dm/dashboard/stats", () =>
        HttpResponse.json({
          items: [
            { category_code: "SOP", category_name: "SOP", count: 0 },
            { category_code: "MANUAL", category_name: "系統操作手冊", count: 0 },
            { category_code: "TRAINING", category_name: "訓練教材", count: 0 },
            { category_code: "OTHER", category_name: "其他", count: 0 },
          ],
          total: 0,
        }),
      ),
    )
    renderWithProviders(<DmDashboardPage />)
    expect(await screen.findByText("SOP")).toBeInTheDocument()
    const totalLine = screen.getByText(/總計/)
    expect(within(totalLine).getByText("0")).toBeInTheDocument()
  })
})
