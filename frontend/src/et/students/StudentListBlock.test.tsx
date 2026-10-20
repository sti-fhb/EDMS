import { screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { StudentListBlock } from "./StudentListBlock"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { formatDateTime } from "../../utils/date"

// 期望值一律由 `formatDateTime` 現算，不寫死字面時刻：該函式依執行環境時區換算，
// 寫死 `2026/04/01 10:00` 會讓非 UTC+8 的機器（含 CI）紅掉（#551）。
const renderBlock = () =>
  renderWithProviders(
    <StudentListBlock courseId={1} readOnly={false} exporting={false} onRemove={vi.fn()} onExport={vi.fn()} onApprove={vi.fn()} />,
  )

describe("StudentListBlock 時間欄（#551）", () => {
  it("加入時間與最後活動經 date.ts 格式化，不再是自寫的 - 分隔格式", async () => {
    renderBlock()
    // 預設 fixture：s01 加入 2026-04-01T02:00:00Z、最後活動 2026-05-02T06:30:00Z
    expect(await screen.findByText(formatDateTime("2026-04-01T02:00:00Z"))).toBeInTheDocument()
    expect(screen.getByText(formatDateTime("2026-05-02T06:30:00Z"))).toBeInTheDocument()
    // 正向錨點先成立，此否定斷言才不會因畫面沒渲染而恆真
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)).not.toBeInTheDocument()
  })

  it("核可時間經 date.ts 格式化", async () => {
    server.use(
      http.get("/api/et/courses/:courseId/students", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "s01",
              user_name: "王小明",
              joined_at: "2026-04-01T02:00:00Z",
              completion_status: "COMPLETED",
              progress_pct: 100,
              avg_score: "88.50",
              last_activity_at: "2026-05-02T06:30:00Z",
              has_in_progress_attempt: false,
              approval_status: "PASSED",
              approval_note: null,
              approved_by_name: "林教師",
              approved_at: "2026-05-03T01:15:00Z",
              approval_version: 1,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderBlock()
    const expected = `林教師 核可 ${formatDateTime("2026-05-03T01:15:00Z")}`
    expect(await screen.findByText(expected)).toBeInTheDocument()
    expect(screen.queryByText(/林教師 核可 \d{4}-\d{2}-\d{2}/)).not.toBeInTheDocument()
  })
})

describe("撤銷核可後的列（#767 ②）", () => {
  // 撤銷只設撤銷欄位、不清核可人／時間／備註（approval/repository.py），後端照實回傳。
  // 狀態已回到「待核可」，那些是已失效的舊核可，顯示出來看起來像「已核可過」。
  function mockRow(approvalStatus: "PENDING" | "FAILED") {
    server.use(
      http.get("/api/et/courses/:courseId/students", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "s01",
              user_name: "王小明",
              joined_at: "2026-04-01T02:00:00Z",
              completion_status: "COMPLETED",
              progress_pct: 100,
              avg_score: "88.50",
              last_activity_at: "2026-05-02T06:30:00Z",
              has_in_progress_attempt: false,
              approval_status: approvalStatus,
              approval_note: "實作未達標準",
              approved_by_name: "林教師",
              approved_at: "2026-05-03T01:15:00Z",
              approval_version: 2,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
  }

  it("待核可（已撤銷）：只顯示狀態，不顯示舊的核可人、時間與備註", async () => {
    mockRow("PENDING")
    renderBlock()
    // 正向錨點：列已渲染（「待核可」字樣在區塊說明列也有，不能拿來當錨點）
    expect(await screen.findByText("王小明")).toBeInTheDocument()
    const chips = Array.from(document.querySelectorAll(".MuiChip-label")).map((el) => el.textContent)
    expect(chips).toContain("待核可")
    expect(screen.queryByText(/林教師 核可/)).not.toBeInTheDocument()
    expect(screen.queryByText("實作未達標準")).not.toBeInTheDocument()
  })

  it("未通過：核可人、時間與備註照常顯示（正向錨點）", async () => {
    mockRow("FAILED")
    renderBlock()
    expect(await screen.findByText(`林教師 核可 ${formatDateTime("2026-05-03T01:15:00Z")}`)).toBeInTheDocument()
    expect(screen.getByText("實作未達標準")).toBeInTheDocument()
  })
})
