import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmObsoletePage } from "./DmObsoletePage"
import { downloadObsoleteCsv } from "./obsoleteService"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy }
})

// 匯出走 axios responseType:blob → jsdom/MSW(XHR) 不相容；partial-mock 下載函式驗接線，
// obsoleteApi（清單查詢）維持真實、走 MSW。
vi.mock("./obsoleteService", async (orig) => {
  const actual = await orig<typeof import("./obsoleteService")>()
  return { ...actual, downloadObsoleteCsv: vi.fn() }
})

beforeEach(() => {
  navigateSpy.mockClear()
  vi.mocked(downloadObsoleteCsv).mockClear()
})

describe("DmObsoletePage 已廢止文件查詢", () => {
  it("列出已廢止文件：末版版號 + 廢止脈絡欄位（原作者＝末版作者 / 申請人 / 核准者 / 原因）", async () => {
    renderWithProviders(<DmObsoletePage />)
    expect(await screen.findByText("停辦作業SOP")).toBeInTheDocument()
    expect(screen.getByText("版本 3.0")).toBeInTheDocument() // 末版版號
    expect(screen.getByText("原作者A")).toBeInTheDocument() // 末版作者（Q2=B）
    expect(screen.getByText("申請人B")).toBeInTheDocument() // 廢止申請人
    expect(screen.getByText("核准者C")).toBeInTheDocument() // 核准者
    expect(screen.getByText("部門裁撤")).toBeInTheDocument() // 廢止原因
  })

  it("空結果 → 顯示 DM-MSG-DM06-001", async () => {
    server.use(
      http.get("/api/dm/obsolete-archive/documents", () =>
        HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
      ),
    )
    renderWithProviders(<DmObsoletePage />)
    expect(await screen.findByText("查無符合條件之已廢止文件。")).toBeInTheDocument()
  })

  it("點文件列 → 導向 US4 read-only 詳細頁", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmObsoletePage />)
    await user.click(await screen.findByText("停辦作業SOP"))
    expect(navigateSpy).toHaveBeenCalledWith("/dm/documents/DM-SOP-000901")
  })

  it("匯出 CSV：點擊觸發下載", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmObsoletePage />)
    await screen.findByText("停辦作業SOP")
    await user.click(screen.getByRole("button", { name: "匯出 CSV" }))
    expect(downloadObsoleteCsv).toHaveBeenCalled()
  })

  it("非管理者（access can_access=false）→ 直接顯示無權限、不渲染搜尋 UI（DM-MSG-DM06-002）", async () => {
    server.use(http.get("/api/dm/obsolete-archive/access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<DmObsoletePage />)
    expect(await screen.findByText("您無權限存取此頁面")).toBeInTheDocument()
    // 搜尋列 / 匯出鈕皆不渲染（不先閃搜尋 UI）
    expect(screen.queryByRole("button", { name: "匯出 CSV" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/關鍵字/)).not.toBeInTheDocument()
  })
})
