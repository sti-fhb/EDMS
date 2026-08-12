import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmLibraryPage } from "./DmLibraryPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy }
})

beforeEach(() => navigateSpy.mockClear())

describe("DmLibraryPage 文件庫", () => {
  it("列出已發布文件：欄位 + 檢索標籤灰字頓號 + 手冊列顯示 func_name", async () => {
    renderWithProviders(<DmLibraryPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    expect(screen.getByText("供應、平時")).toBeInTheDocument() // 檢索標籤頓號分隔
    expect(screen.getByText("BS04 — 領血確認")).toBeInTheDocument() // 手冊列 func_name
  })

  it("分類選「系統操作手冊」→ 條件式顯示 func_name 下拉", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmLibraryPage />)
    await screen.findByText("領血確認標準作業程序")
    expect(screen.queryByRole("combobox", { name: /關聯作業項目/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: "分類" }))
    await user.click(await screen.findByRole("option", { name: "系統操作手冊" }))
    expect(await screen.findByRole("combobox", { name: /關聯作業項目/ })).toBeInTheDocument()
  })

  it("檢索標籤下拉列出檢索標籤（供應 / 平時）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmLibraryPage />)
    await screen.findByText("領血確認標準作業程序")
    await user.click(screen.getByRole("combobox", { name: /檢索標籤/ }))
    expect(await screen.findByRole("option", { name: "供應" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "平時" })).toBeInTheDocument()
  })

  it("新增文件入口：can_create=true 顯示", async () => {
    renderWithProviders(<DmLibraryPage />)
    expect(await screen.findByRole("button", { name: "新增文件" })).toBeInTheDocument()
  })

  it("新增文件入口：can_create=false 不顯示", async () => {
    server.use(http.get("/api/dm/library/capabilities", () => HttpResponse.json({ can_create: false })))
    renderWithProviders(<DmLibraryPage />)
    await screen.findByText("領血確認標準作業程序")
    expect(screen.queryByRole("button", { name: "新增文件" })).not.toBeInTheDocument()
  })

  it("空結果 → 顯示查無提示", async () => {
    server.use(
      http.get("/api/dm/library/documents", () =>
        HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
      ),
    )
    renderWithProviders(<DmLibraryPage />)
    expect(await screen.findByText("查無符合條件之文件。")).toBeInTheDocument()
  })

  it("點文件列 → 導向文件詳細頁（US4 路由）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmLibraryPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    expect(navigateSpy).toHaveBeenCalledWith("/dm/documents/DM-SOP-000001")
  })
})
