import { screen, within } from "@testing-library/react"
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
    // 統計卡：整體平均閱讀率 + 低於 50% 文件數（旁附總文件數）
    expect(screen.getByText("整體平均閱讀率")).toBeInTheDocument()
    expect(screen.getByText("閱讀率低於 50% 之文件數")).toBeInTheDocument()
    // 分母是 rated_docs（1）而非 total_docs（2）：分子只計可算閱讀率者，母體必須相同（#567 C）。
    // 本行原本斷言「／ 共 2 份文件」——那個值把應看=0 的文件也放進分母，與分子母體不符。
    expect(screen.getByText("／ 共 1 份可計算文件")).toBeInTheDocument()
    // 應看=0 文件 → 顯示「—（無對應閱覽者）」
    expect(screen.getByText("—（無對應閱覽者）")).toBeInTheDocument()
  })

  it("展開文件 → 逐可見對象組明細，且說明分組加總大於文件總計", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmKpiPage />)
    await screen.findByText("領血確認標準作業程序")
    // 收合時與加此功能之前完全相同：組名不出現
    expect(screen.queryByText("醫檢師")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "展開 領血確認標準作業程序 的可見對象" }))

    // 正向錨點：展開後兩組都在（與上面的否定式用同一種查詢，避免文案改動時只有正向會紅）
    expect(await screen.findByText("醫檢師")).toBeInTheDocument()
    expect(screen.getByText("國防醫學院三軍總醫院松山分院．護理師")).toBeInTheDocument()
    // fixture 刻意讓兩組重疊（6 + 5 = 11 > 應看 10）。這句話不是裝飾：缺了它，
    // 看的人會把對不起來的兩個數字判定成算錯。
    expect(
      screen.getByText(
        "分組「應看」加總為 11，大於本文件應看 10：有人同時符合多組，各組分母都計入他，文件總計則已去重。",
      ),
    ).toBeInTheDocument()
  })

  it("分組加總等於文件總計時 → 不顯示重疊說明", async () => {
    // 身兼多組是少數例外。無條件顯示會讓常態多出一句說明一件沒發生的事，
    // 甚至印出「加總（2）可能大於本文件應看（2）」這種自我矛盾的句子（裁示 2026-10-08）。
    const user = userEvent.setup()
    renderWithProviders(<DmKpiPage />)
    await screen.findByText("無重疊文件")

    await user.click(screen.getByRole("button", { name: "展開 無重疊文件 的可見對象" }))

    // 正向錨點：展開確實生效（與下方否定式同為 text 查詢，避免「找不到」造成恆真）
    expect(await screen.findByText("軍人")).toBeInTheDocument()
    expect(screen.queryByText(/分組「應看」加總為/)).not.toBeInTheDocument()
  })

  it("命中的全是訓練教材時 → 不顯示統計卡與文件統計區塊", async () => {
    server.use(
      http.get("/api/dm/kpi/documents", () =>
        HttpResponse.json({
          data: [],
          meta: { total: 0, page: 1, limit: 20, total_pages: 0 },
          summary: { total_docs: 0, rated_docs: 0, overall_rate: null, below_50_count: 0 },
          training_docs: [
            { doc_id: "DM-TRAINING-000001", doc_name: "基礎輸血學", category_name: "訓練教材", current_version_no: "1.0" },
          ],
          training_total: 1,
        }),
      ),
    )
    renderWithProviders(<DmKpiPage />)

    // 正向錨點：訓練教材區照常呈現（證明頁面有載入，否定式才有意義）
    expect(await screen.findByText("訓練教材（共 1 份）")).toBeInTheDocument()
    // 統計必然為空（訓練教材不進統計母體），再顯示「—／共 0 份」與「查無符合條件」只是噪音
    expect(screen.queryByText("整體平均閱讀率")).not.toBeInTheDocument()
    expect(screen.queryByText("閱讀率低於 50% 之文件數")).not.toBeInTheDocument()
    expect(screen.queryByText("查無符合條件之文件統計")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "匯出 CSV" })).not.toBeInTheDocument()
  })

  it("訓練教材另成一區，且該區不含任何閱讀統計欄位", async () => {
    renderWithProviders(<DmKpiPage />)
    expect(await screen.findByText("訓練教材（共 1 份）")).toBeInTheDocument()
    expect(screen.getByText("基礎輸血學")).toBeInTheDocument()
    expect(screen.getByText(/閱讀由教育訓練模組追蹤/)).toBeInTheDocument()

    // 以「該區的欄位正好是這三個」正向證明沒有統計欄，而非斷言某個字串不存在
    // （後者在主表也有「應看」欄的情況下無法區分，且找不到時恆真）
    const section = screen.getByText("訓練教材（共 1 份）").closest(".MuiPaper-root") as HTMLElement
    const headers = within(section)
      .getAllByRole("columnheader")
      .map((h) => h.textContent)
    expect(headers).toEqual(["文件", "分類", "目前版本"])
  })

  it("分類下拉取自後端：後台新增的分類也列得出來", async () => {
    // 「院內公告」只存在於 API fixture，不在任何前端常數裡——此前本頁的分類下拉是寫死的
    // 4 筆，後台新增的分類在這裡篩不到（#483 第 1 項）。
    const user = userEvent.setup()
    renderWithProviders(<DmKpiPage />)
    await screen.findByText("領血確認標準作業程序")

    await user.click(screen.getByRole("combobox", { name: "分類" }))

    expect(await screen.findByRole("option", { name: "院內公告" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "標準作業程序" })).toBeInTheDocument()
  })

  it("空結果 → 顯示 DM-MSG-DM06-001", async () => {
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

  it("非管理者（admin-access can_access=false）→ 直接顯示無權限、不渲染查詢 UI（DM-MSG-DM06-002）", async () => {
    server.use(http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<DmKpiPage />)
    expect(await screen.findByText("您無權限存取此頁面")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "匯出 CSV" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("分類")).not.toBeInTheDocument()
  })
})
