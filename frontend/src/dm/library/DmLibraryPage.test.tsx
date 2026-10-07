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

  it("分類下拉取自後端：後台新增的分類也列得出來、名稱用 DB 值", async () => {
    // 「院內公告」只存在於 API fixture，不在任何前端常數裡——此前下拉寫死 4 筆，後台新增的
    // 分類可以拿來建文件卻在查詢頁篩不到（#483 第 1 項）。
    const user = userEvent.setup()
    renderWithProviders(<DmLibraryPage />)
    await screen.findByText("領血確認標準作業程序")

    await user.click(screen.getByRole("combobox", { name: "分類" }))

    expect(await screen.findByRole("option", { name: "院內公告" })).toBeInTheDocument()
    // 名稱取自 DB，不再是前端常數的「SOP（標準作業程序）」
    expect(screen.getByRole("option", { name: "標準作業程序" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "SOP（標準作業程序）" })).not.toBeInTheDocument()
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

describe("DmLibraryPage 發布日期（#539）", () => {
  it("以台灣時間呈現：UTC 前一天 17:30 顯示為台灣隔日", async () => {
    server.use(
      http.get("/api/dm/library/documents", () =>
        HttpResponse.json({
          data: [
            {
              doc_id: "DM-SOP-000001",
              doc_name: "領血確認標準作業程序",
              category_code: "SOP",
              category_name: "SOP",
              published_date: "2026-10-05T17:30:00Z",
              author_id: "u1",
              author_name: "陳大華",
              func_code: null,
              func_name: null,
              tags: [],
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<DmLibraryPage />)
    expect(await screen.findByText("2026-10-06")).toBeInTheDocument()
    expect(screen.queryByText("2026-10-05")).not.toBeInTheDocument()
  })
})
