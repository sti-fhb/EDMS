import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmKpiPage } from "./DmKpiPage"
import { downloadKpiCsv } from "./kpiService"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// 匯出走 axios responseType:blob → jsdom/MSW(XHR) 不相容；partial-mock 下載函式驗接線，
// kpiApi（清單查詢）維持真實、走 MSW。
vi.mock("./kpiService", async (orig) => {
  const actual = await orig<typeof import("./kpiService")>()
  return { ...actual, downloadKpiCsv: vi.fn() }
})

beforeEach(() => {
  vi.mocked(downloadKpiCsv).mockClear()
})

describe("DmKpiPage 閱讀統計 KPI", () => {
  it("列出逐文件 KPI：文件 / 分類 / 版本 / 應看 / 已看 / 未看 / 閱讀率 + 統計卡", async () => {
    renderWithProviders(<DmKpiPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    // 閱讀率（統計卡 overall 與該列 rate 同為 40.0%，故至少 1 處）
    expect(screen.getAllByText("40.0%").length).toBeGreaterThanOrEqual(1)
    // 統計卡：整體平均閱讀率 + 低於 50% 文件數
    expect(screen.getByText("整體平均閱讀率")).toBeInTheDocument()
    expect(screen.getByText("閱讀率低於 50% 之文件數")).toBeInTheDocument()
    // 應看=0 文件 → 顯示「—（無對應閱覽者）」
    expect(screen.getByText("—（無對應閱覽者）")).toBeInTheDocument()
  })

  it("空結果 → 顯示 DM-MSG-DM10-001", async () => {
    server.use(
      http.get("/api/dm/kpi/documents", () =>
        HttpResponse.json({
          data: [],
          meta: { total: 0, page: 1, limit: 20, total_pages: 0 },
          summary: { total_docs: 0, overall_rate: null, below_50_count: 0 },
        }),
      ),
    )
    renderWithProviders(<DmKpiPage />)
    expect(await screen.findByText("查無符合條件之文件統計")).toBeInTheDocument()
  })

  it("匯出 CSV：點擊觸發下載", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmKpiPage />)
    await screen.findByText("領血確認標準作業程序")
    await user.click(screen.getByRole("button", { name: "匯出 CSV" }))
    expect(downloadKpiCsv).toHaveBeenCalled()
  })

  it("非管理者（admin-access can_access=false）→ 直接顯示無權限、不渲染查詢 UI（DM-MSG-DM10-002）", async () => {
    server.use(http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<DmKpiPage />)
    expect(await screen.findByText("您無權限存取此頁面")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "匯出 CSV" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("分類")).not.toBeInTheDocument()
  })
})
