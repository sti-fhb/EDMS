import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AuditPage } from "./AuditPage"
import { auditApi } from "./auditService"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

describe("AuditPage 操作記錄查詢（唯讀）", () => {
  it("列出稽核紀錄：結果 badge、操作者姓名、功能中文、對象解析名", async () => {
    renderWithProviders(<AuditPage />)

    expect(await screen.findByText("SUCCESS")).toBeInTheDocument()
    expect(screen.getByText("FAIL")).toBeInTheDocument()
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    // 無 operator_name / email 之列（SYSTEM）fallback 顯示原 ID
    expect(screen.getByText("SYSTEM")).toBeInTheDocument()
    // 功能顯示中文（func_label），非原碼 DP-USERS
    expect(screen.getByText("使用者管理")).toBeInTheDocument()
    expect(screen.queryByText("DP-USERS")).not.toBeInTheDocument()
    // 對象顯示解析後名稱（target_display）
    expect(screen.getByText("林小美")).toBeInTheDocument()
  })

  it("查無紀錄 → 顯示空狀態提示（AUDIT-001）", async () => {
    server.use(
      http.get("/api/dp/audit/logs", () =>
        HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
      ),
    )
    renderWithProviders(<AuditPage />)

    expect(await screen.findByText("查無符合條件之紀錄")).toBeInTheDocument()
  })

  it("點明細 → 開 modal 顯示前後值（JSON 格式化）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("SUCCESS")

    await user.click(screen.getAllByRole("button", { name: "明細" })[0])

    expect(await screen.findByText("操作記錄明細")).toBeInTheDocument()
    expect(screen.getByText("異動前值")).toBeInTheDocument()
    // JSON 格式化後含 status 鍵值
    expect(screen.getByText(/"status": "ACTIVE"/)).toBeInTheDocument()
  })

  it("介面無任何新增 / 編輯 / 刪除按鈕（append-only 唯讀）", async () => {
    renderWithProviders(<AuditPage />)
    await screen.findByText("SUCCESS")

    expect(screen.queryByRole("button", { name: /新增|建立|編輯|刪除/ })).not.toBeInTheDocument()
  })

  it("即時篩選：無「查詢」按鈕，有「清除篩選」；點清除重置條件", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("SUCCESS")

    expect(screen.queryByRole("button", { name: "查詢" })).not.toBeInTheDocument()
    const operatorInput = screen.getByLabelText("操作者（姓名 / Email）")
    await user.type(operatorInput, "王")
    expect(operatorInput).toHaveValue("王")

    await user.click(screen.getByRole("button", { name: "清除篩選" }))
    expect(operatorInput).toHaveValue("")
  })

  it("點匯出 → 取回 CSV blob 並觸發下載", async () => {
    // MSW + jsdom XHR 對 blob 回應不相容，改 spy service 層回 Blob，專注驗下載觸發邏輯
    const exportSpy = vi.spyOn(auditApi, "exportCsv").mockResolvedValue(new Blob(["﻿LOG_ID\n1\n"], { type: "text/csv" }))
    const createUrl = vi.fn(() => "blob:audit")
    // @ts-expect-error jsdom 未實作 createObjectURL，測試以 mock 補上
    global.URL.createObjectURL = createUrl
    // @ts-expect-error jsdom 未實作 revokeObjectURL，測試以 mock 補上
    global.URL.revokeObjectURL = vi.fn()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})

    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("SUCCESS")

    await user.click(screen.getByRole("button", { name: "匯出" }))

    await waitFor(() => expect(exportSpy).toHaveBeenCalled())
    expect(createUrl).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
  })

  beforeEach(() => {
    localStorage.setItem("authToken", "test-token")
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })
})