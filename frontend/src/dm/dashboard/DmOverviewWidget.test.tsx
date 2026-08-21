import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmOverviewWidget } from "./DmOverviewWidget"
import { server } from "../../test/server"
import { renderWithProviders } from "../../test/renderWithProviders"

// useNavigate 監看導向（公告點入 / 查看全部）
const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy }
})

describe("DmOverviewWidget 中性歡迎頁之 DM 文件概況（DM00）", () => {
  beforeEach(() => navigateSpy.mockClear())

  it("統計卡：4 內建分類數量 + 總計", async () => {
    renderWithProviders(<DmOverviewWidget />)
    expect(await screen.findByText("SOP")).toBeInTheDocument()
    expect(screen.getByText("系統操作手冊")).toBeInTheDocument()
    expect(screen.getByText("訓練教材")).toBeInTheDocument()
    expect(screen.getByText("其他")).toBeInTheDocument()
    expect(screen.getByText("42")).toBeInTheDocument()
    expect(screen.getByText(/總計/)).toBeInTheDocument()
    expect(screen.getByText("76")).toBeInTheDocument()
  })

  it("最新更新公告：列出近 30 天發布 + 新增(綠)/新版本(藍) badge", async () => {
    renderWithProviders(<DmOverviewWidget />)
    expect(await screen.findByText("用血回報訓練教材")).toBeInTheDocument()
    expect(screen.getByText("領血確認標準作業程序")).toBeInTheDocument()
    const addBadge = screen.getByText(/新增 1\.0/).closest(".MuiChip-root") as HTMLElement
    const verBadge = screen.getByText(/新版本 2\.1/).closest(".MuiChip-root") as HTMLElement
    // 新增＝success(綠)、新版本＝info(藍)；不得為 primary（本主題品牌綠、與 success 難分）
    expect(addBadge).toHaveClass("MuiChip-colorSuccess")
    expect(verBadge).toHaveClass("MuiChip-colorInfo")
    expect(screen.getByRole("button", { name: /查看全部文件/ })).toBeInTheDocument()
  })

  it("點公告列導向該文件詳細頁", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmOverviewWidget />)
    const row = (await screen.findByText("用血回報訓練教材")).closest("[role=button]") as HTMLElement
    await user.click(row)
    expect(navigateSpy).toHaveBeenCalledWith("/dm/documents/DM-TRAINING-000010")
  })

  it("點「查看全部文件」導向文件庫", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmOverviewWidget />)
    await user.click(await screen.findByRole("button", { name: /查看全部文件/ }))
    expect(navigateSpy).toHaveBeenCalledWith("/dm/library")
  })

  it("載入失敗：統計與公告各顯示錯誤提示（非偽裝成空狀態）", async () => {
    server.use(
      http.get("/api/dm/dashboard/stats", () => new HttpResponse(null, { status: 500 })),
      http.get("/api/dm/dashboard/announcements", () => new HttpResponse(null, { status: 500 })),
    )
    renderWithProviders(<DmOverviewWidget />)
    const errors = await screen.findAllByText("載入失敗，請稍後再試。")
    expect(errors).toHaveLength(2)
    expect(screen.queryByText("近期無新發布文件")).not.toBeInTheDocument()
  })

  it("公告空狀態：近 30 天無事件顯示提示（DM-MSG-DM00-001）", async () => {
    server.use(http.get("/api/dm/dashboard/announcements", () => HttpResponse.json([])))
    renderWithProviders(<DmOverviewWidget />)
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
    renderWithProviders(<DmOverviewWidget />)
    expect(await screen.findByText("SOP")).toBeInTheDocument()
    const totalLine = screen.getByText(/總計/)
    expect(within(totalLine).getByText("0")).toBeInTheDocument()
  })
})
