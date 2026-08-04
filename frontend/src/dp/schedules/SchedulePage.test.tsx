import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { SchedulePage } from "./SchedulePage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 覆寫 SCHDP001 歷程 handler（供結果顯示測試指定 status）。 */
function useLogs(rows: { log_id: number; status: string | null; error_msg: string | null }[]) {
  server.use(
    http.get("/api/dp/schedules/SCHDP001/logs", () =>
      HttpResponse.json({
        data: rows.map((r) => ({
          ...r,
          job_id: "SCHDP001",
          start_date: "2026-07-06T08:00:00Z",
          end_date: "2026-07-06T08:00:41Z",
        })),
        meta: { total: rows.length, page: 1, limit: 20, total_pages: 1 },
      }),
    ),
  )
}

/** 開啟 SCHDP001 的執行歷程 Dialog。 */
async function openFirstLogs(user: ReturnType<typeof userEvent.setup>) {
  renderWithProviders(<SchedulePage />)
  await screen.findByText(/SCHDP001/)
  await user.click(screen.getAllByRole("button", { name: "執行歷程" })[0])
  return screen.findByRole("dialog")
}

describe("SchedulePage 排程作業總覽（可編輯）", () => {
  it("列出排程 job（cron / 狀態 / 最近執行 / 下次執行）", async () => {
    renderWithProviders(<SchedulePage />)

    expect(await screen.findByText(/SCHDP001/)).toBeInTheDocument()
    expect(screen.getByText("0 8 * * *")).toBeInTheDocument()
    // 欄位標題：狀態（原「啟停」）、下次執行；無「結果」欄
    expect(screen.getByRole("columnheader", { name: "狀態" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "下次執行" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "結果" })).not.toBeInTheDocument()
    expect(screen.getByText("啟用")).toBeInTheDocument()
    expect(screen.getByText("停用")).toBeInTheDocument() // ET 預留列
  })

  it("點歷程 → 開 Dialog 顯示執行歷程", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    await user.click(screen.getAllByRole("button", { name: "執行歷程" })[0])

    expect(await screen.findByText(/執行歷程/)).toBeInTheDocument()
    expect(screen.getByText("錯誤 / 跳過原因")).toBeInTheDocument()
  })

  it("無歷程之 job → 空狀態 SCHEDULE-001", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHET001/)

    await user.click(screen.getAllByRole("button", { name: "執行歷程" })[1])

    expect(await screen.findByText("尚無排程執行紀錄")).toBeInTheDocument()
  })

  it("點編輯 → 開 Dialog（JOB_ID 唯讀）→ 改名/cron/啟停儲存 → 成功提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    await user.click(screen.getAllByRole("button", { name: "編輯" })[0])
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByLabelText("Job ID")).toBeDisabled()

    const name = within(dialog).getByLabelText(/作業名稱/)
    await user.clear(name)
    await user.type(name, "平台每日作業（改）")
    await user.click(within(dialog).getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("排程已更新")).toBeInTheDocument()
  })

  it("執行歷程結果顯示中文（成功 / 失敗 / 跳過），不顯示英文碼", async () => {
    const user = userEvent.setup()
    useLogs([
      { log_id: 3, status: "SUCCESS", error_msg: null },
      { log_id: 2, status: "FAILED", error_msg: "連線逾時" },
      { log_id: 1, status: "SKIPPED", error_msg: "前次執行尚未完成" },
    ])

    const dialog = await openFirstLogs(user)

    expect(await within(dialog).findByText("成功")).toBeInTheDocument()
    expect(within(dialog).getByText("失敗")).toBeInTheDocument()
    expect(within(dialog).getByText("跳過")).toBeInTheDocument()
    expect(within(dialog).queryByText("SUCCESS")).not.toBeInTheDocument()
    expect(within(dialog).queryByText("FAILED")).not.toBeInTheDocument()
    expect(within(dialog).queryByText("SKIPPED")).not.toBeInTheDocument()
  })

  it("結果 Chip 配色：成功綠 / 失敗紅（判斷仍依英文碼）", async () => {
    const user = userEvent.setup()
    useLogs([
      { log_id: 2, status: "SUCCESS", error_msg: null },
      { log_id: 1, status: "FAILED", error_msg: "連線逾時" },
    ])

    const dialog = await openFirstLogs(user)

    expect(await within(dialog).findByText("成功")).toBeInTheDocument()
    expect(within(dialog).getByText("成功").closest(".MuiChip-root")).toHaveClass("MuiChip-colorSuccess")
    expect(within(dialog).getByText("失敗").closest(".MuiChip-root")).toHaveClass("MuiChip-colorError")
  })

  it("status 為 null → 結果欄顯示 —", async () => {
    const user = userEvent.setup()
    useLogs([{ log_id: 1, status: null, error_msg: "執行中" }])

    const dialog = await openFirstLogs(user)
    await within(dialog).findByText("執行中")

    // 欄序：起 / 訖 / 結果 / 錯誤；[0] 為表頭列
    const cells = within(within(dialog).getAllByRole("row")[1]).getAllByRole("cell")
    expect(cells[2]).toHaveTextContent("—")
  })

  it("無手動補跑按鈕（補跑不開放）", async () => {
    renderWithProviders(<SchedulePage />)
    await screen.findByText(/SCHDP001/)

    expect(
      screen.queryByRole("button", { name: /補跑|重跑|手動執行|立即執行/ }),
    ).not.toBeInTheDocument()
  })
})