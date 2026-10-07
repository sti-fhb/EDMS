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
    <StudentListBlock courseId={1} readOnly={false} onRemove={vi.fn()} onExport={vi.fn()} onApprove={vi.fn()} />,
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
