import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmChangeLogPage } from "./DmChangeLogPage"
import { downloadChangeLogCsv } from "./changeLogService"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// 匯出走 axios responseType:blob → jsdom/MSW(XHR) 不相容；partial-mock 下載函式驗接線，
// changeLogApi（清單查詢）維持真實、走 MSW。
vi.mock("./changeLogService", async (orig) => {
  const actual = await orig<typeof import("./changeLogService")>()
  return { ...actual, downloadChangeLogCsv: vi.fn() }
})

beforeEach(() => {
  vi.mocked(downloadChangeLogCsv).mockClear()
})

describe("DmChangeLogPage 文件變更歷程查詢", () => {
  it("列出變更紀錄：時間 / 申請人 / 核准人 / 操作 badge / 文件 / 版本 / 備註", async () => {
    renderWithProviders(<DmChangeLogPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    expect(screen.getByText("補充異常通報流程")).toBeInTheDocument() // 備註（發布＝變更摘要）
    expect(screen.getByText("院內急救業務調整，本流程不再執行")).toBeInTheDocument() // 廢止原因
    // 操作 badge：發布 + 廢止
    expect(screen.getByText("發布")).toBeInTheDocument()
    expect(screen.getByText("廢止")).toBeInTheDocument()
    // 申請人 / 核准人
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    expect(screen.getByText("王曉明")).toBeInTheDocument()
    expect(screen.getAllByText("李主任").length).toBeGreaterThan(0)
  })

  it("空結果 → 顯示 DM-MSG-DM08-001", async () => {
    server.use(
      http.get("/api/dm/change-log/entries", () =>
        HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
      ),
    )
    renderWithProviders(<DmChangeLogPage />)
    expect(await screen.findByText("查無符合條件之變更紀錄。")).toBeInTheDocument()
  })

  it("匯出 CSV：點擊觸發下載", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmChangeLogPage />)
    await screen.findByText("領血確認標準作業程序")
    await user.click(screen.getByRole("button", { name: "匯出 CSV" }))
    expect(downloadChangeLogCsv).toHaveBeenCalled()
  })

  it("非管理者（admin-access can_access=false）→ 直接顯示無權限、不渲染搜尋 UI（DM-MSG-DM08-002）", async () => {
    server.use(http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<DmChangeLogPage />)
    expect(await screen.findByText("您無權限存取此頁面")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "匯出 CSV" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("操作類型")).not.toBeInTheDocument()
  })
})
