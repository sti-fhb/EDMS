import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { AttemptOverviewBlock } from "./AttemptOverviewBlock"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { formatDateTime } from "../../utils/date"

describe("AttemptOverviewBlock 交卷時間（#551）", () => {
  it("經 date.ts 格式化，不再是 toLocaleString 的上午／下午與秒數", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    // 預設 fixture：王小明「基本概念測驗」兩次作答，交卷於 2026-04-22T02:12Z、2026-05-02T06:05Z
    await user.click(await screen.findByRole("button", { name: /王小明/ }))
    // 期望值由 formatDateTime 現算，不寫死字面時刻（依執行環境時區換算）
    expect(await screen.findByText(formatDateTime("2026-04-22T02:12:00Z"))).toBeInTheDocument()
    expect(screen.getByText(formatDateTime("2026-05-02T06:05:00Z"))).toBeInTheDocument()
    expect(screen.queryByText(/上午|下午/)).not.toBeInTheDocument()
  })
})

describe("AttemptOverviewBlock 輪次分段（#709）", () => {
  it("要求重測後於新一輪前插分隔列，舊輪標「前一輪」", async () => {
    server.use(
      http.get("/api/et/courses/:courseId/attempt-overview", () =>
        HttpResponse.json({
          students: [
            {
              user_id: "s01",
              user_name: "王小明",
              quizzes: [
                {
                  quiz_id: 1,
                  quiz_name: "基本概念測驗",
                  max_retry: 3,
                  used_attempts: 1,
                  is_passed: false,
                  can_reset: false,
                  attempts: [
                    { attempt_id: 11, attempt_no: 1, submitted_at: "2026-09-30T02:41:00Z", score: "100.00", points_total: 100, is_pass: true },
                    { attempt_id: 12, attempt_no: 2, submitted_at: "2026-10-14T09:04:00Z", score: "25.00", points_total: 100, is_pass: false },
                  ],
                  resets: [{ after_attempt_no: 1, kind: "RETEST", executed_at: "2026-10-14T09:00:00Z" }],
                },
              ],
            },
          ],
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: /王小明/ }))

    expect(await screen.findByText(/教師要求重測（測驗內容已更新）/)).toBeInTheDocument()
    expect(screen.getByRole("row", { name: /第 1 次/ })).toHaveTextContent("前一輪")
    expect(screen.getByRole("row", { name: /第 2 次/ })).not.toHaveTextContent("前一輪")
  })
})

describe("重置鈕的說明（#768 第 1 項）", () => {
  // 原本先看 can_reset：學員符合重置條件、但課程已關閉時，鈕是灰的，說明卻寫「重置後該學員可再作答」
  function mockResettable() {
    server.use(
      http.get("/api/et/courses/:courseId/attempt-overview", () =>
        HttpResponse.json({
          students: [
            {
              user_id: "s01",
              user_name: "王小明",
              quizzes: [
                {
                  quiz_id: 1,
                  quiz_name: "基本概念測驗",
                  max_retry: 0,
                  used_attempts: 1,
                  is_passed: false,
                  can_reset: true,
                  attempts: [
                    { attempt_id: 11, attempt_no: 1, submitted_at: "2026-09-30T02:41:00Z", score: "40.00", points_total: 100, is_pass: false },
                  ],
                  resets: [],
                },
              ],
            },
          ],
        }),
      ),
    )
  }

  async function hoverReset(readOnly: boolean) {
    mockResettable()
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={readOnly} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: /王小明/ }))
    const button = await screen.findByRole("button", { name: "重置重考次數" })
    await user.hover(button.parentElement as HTMLElement)
    return { button, tooltip: await screen.findByRole("tooltip") }
  }

  it("唯讀（課程已關閉）：說明為課程已關閉，不寫「可再作答」", async () => {
    const { button, tooltip } = await hoverReset(true)
    expect(button).toBeDisabled()
    expect(tooltip).toHaveTextContent("課程已關閉，無法重置")
    expect(tooltip).not.toHaveTextContent("重置後該學員可再作答")
  })

  it("可重置且非唯讀：照舊說明「重置後該學員可再作答」（正向錨點）", async () => {
    const { button, tooltip } = await hoverReset(false)
    expect(button).toBeEnabled()
    expect(tooltip).toHaveTextContent("重置後該學員可再作答")
  })
})
