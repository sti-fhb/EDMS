import { screen, waitFor, within } from "@testing-library/react"
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

    expect(await screen.findByText("成功")).toBeInTheDocument()
    expect(screen.getByText("失敗")).toBeInTheDocument()
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    // 無 operator_name / email 之列（SYSTEM）fallback 顯示原 ID
    expect(screen.getByText("SYSTEM")).toBeInTheDocument()
    // 功能顯示中文（func_label），非原碼 DP-USERS
    expect(screen.getByText("DP-使用者管理")).toBeInTheDocument()
    expect(screen.queryByText("DP-USERS")).not.toBeInTheDocument()
    // 對象顯示解析後名稱（target_display）
    expect(screen.getByText("林小美")).toBeInTheDocument()
  })

  it("操作類別 / 執行結果下拉顯示中文選項，不顯示英文碼", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

    await user.click(screen.getByRole("combobox", { name: "操作類別" }))
    expect(await screen.findByRole("option", { name: "登入" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "刪除" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "LOGIN" })).not.toBeInTheDocument()
    await user.keyboard("{Escape}")

    await user.click(screen.getByRole("combobox", { name: "執行結果" }))
    expect(await screen.findByRole("option", { name: "失敗" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "FAIL" })).not.toBeInTheDocument()
  })

  it("選中文選項 → 送出 API 仍為英文碼（操作類別 / 執行結果皆是）", async () => {
    const seen: { action: string | null; result: string | null }[] = []
    server.use(
      http.get("/api/dp/audit/logs", ({ request }) => {
        const params = new URL(request.url).searchParams
        seen.push({ action: params.get("action_type"), result: params.get("result") })
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("查無符合條件之紀錄")

    await user.click(screen.getByRole("combobox", { name: "執行結果" }))
    await user.click(await screen.findByRole("option", { name: "失敗" }))
    await waitFor(() => expect(seen.some((s) => s.result === "FAIL")).toBe(true))

    await user.click(screen.getByRole("combobox", { name: "操作類別" }))
    await user.click(await screen.findByRole("option", { name: "刪除" }))
    await waitFor(() => expect(seen.some((s) => s.action === "DELETE")).toBe(true))
  })

  it("表格類別 / 結果顯示中文，且配色仍依英文碼判定", async () => {
    renderWithProviders(<AuditPage />)

    expect(await screen.findByText("修改")).toBeInTheDocument()
    expect(screen.getByText("登入")).toBeInTheDocument()
    expect(screen.queryByText("UPDATE")).not.toBeInTheDocument()
    expect(screen.getByText("成功").closest(".MuiChip-root")).toHaveClass("MuiChip-colorSuccess")
    expect(screen.getByText("失敗").closest(".MuiChip-root")).toHaveClass("MuiChip-colorError")
  })

  it("明細 modal 的操作類別 / 執行結果顯示中文", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

    await user.click(screen.getAllByRole("button", { name: "明細" })[0])
    const dialog = await screen.findByRole("dialog")

    expect(within(dialog).getByText("修改")).toBeInTheDocument()
    expect(within(dialog).getByText("成功")).toBeInTheDocument()
    expect(within(dialog).queryByText("UPDATE")).not.toBeInTheDocument()
    expect(within(dialog).queryByText("SUCCESS")).not.toBeInTheDocument()
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
    await screen.findByText("成功")

    await user.click(screen.getAllByRole("button", { name: "明細" })[0])

    expect(await screen.findByText("操作記錄明細")).toBeInTheDocument()
    expect(screen.getByText("異動前值")).toBeInTheDocument()
    // JSON 格式化後含 status 鍵值
    expect(screen.getByText(/"status": "ACTIVE"/)).toBeInTheDocument()
  })

  it("介面無任何新增 / 編輯 / 刪除按鈕（append-only 唯讀）", async () => {
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

    expect(screen.queryByRole("button", { name: /新增|建立|編輯|刪除/ })).not.toBeInTheDocument()
  })

  it("即時篩選：無「查詢」按鈕，有「清除篩選」；點清除重置條件", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

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
    await screen.findByText("成功")

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
describe("AuditPage 篩選選項來自後端（#477）", () => {
  beforeEach(() => {
    localStorage.setItem("authToken", "test-token")
  })

  it("功能下拉列出三個模組的功能，ET 不再缺席", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

    await user.click(screen.getByRole("combobox", { name: "功能" }))

    // #477 之前前端硬編碼清單只有 DP / DM，ET 整組缺席
    expect(await screen.findByRole("option", { name: "ET-課程維護" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "DM-文件編輯" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "DP-登入登出" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "ET-COURSE" })).not.toBeInTheDocument() // 不顯示原碼
  })

  it("操作類別含「匯出」——#322 導入後下拉有、後端值域沒有，選了會 422", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("成功")

    await user.click(screen.getByRole("combobox", { name: "操作類別" }))

    expect(await screen.findByRole("option", { name: "匯出" })).toBeInTheDocument()
  })

  it("選模組 → 送出 API 帶英文碼 module", async () => {
    const seen: (string | null)[] = []
    server.use(
      http.get("/api/dp/audit/logs", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("module"))
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    await screen.findByText("查無符合條件之紀錄")

    await user.click(screen.getByRole("combobox", { name: "模組" }))
    await user.click(await screen.findByRole("option", { name: "教育訓練" }))

    // 送的是 ET 而非「教育訓練」——下拉顯示中文、API 收英文碼
    await waitFor(() => expect(seen).toContain("ET"))
  })

  it("選項端點失敗時下拉為空、列表降級為原碼，不退回任何硬編碼清單", async () => {
    server.use(http.get("/api/dp/audit/options", () => new HttpResponse(null, { status: 500 })))
    const user = userEvent.setup()
    renderWithProviders(<AuditPage />)
    // 等待錨點不可用「成功」——那是 options 轉出來的中文，正是本情境下會消失的東西。
    // 改用 func_label（由列表回應自帶、與 options 無關）。
    await screen.findByText("DP-使用者管理")

    // 降級為原碼而非空白：使用者看得到可辨識的值並能回報，空白會讓人以為該欄沒資料
    expect(screen.getByText("SUCCESS")).toBeInTheDocument()

    await user.click(screen.getByRole("combobox", { name: "功能" }))

    // 只剩「全部」sentinel。若哪天有人「為了保險」在前端留一份 fallback 清單，本條會紅——
    // 那份 fallback 正是 #477 的病灶（看起來有選項、實際與後端不同步）。
    expect(await screen.findByRole("option", { name: "全部" })).toBeInTheDocument()
    expect(screen.getAllByRole("option")).toHaveLength(1)
  })
})

describe("AuditPage 日期上限（#539）", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("台灣時間凌晨（UTC 仍是前一天）時，起日與訖日的上限為台灣當日", async () => {
    // 只假造 Date；計時器仍用真的，MSW 與 React 的非同步更新才不會卡住
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date("2026-10-05T17:30:00Z")) // 台灣 10/06 01:30
    renderWithProviders(<AuditPage />)
    // 原本以 `new Date().toISOString().slice(0, 10)` 取 UTC 當日，此時點上限停在 10/05，選不到今天
    expect(await screen.findByLabelText("訖日")).toHaveAttribute("max", "2026-10-06")
    expect(screen.getByLabelText("起日")).toHaveAttribute("max", "2026-10-06")
  })
})
