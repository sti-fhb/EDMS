import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { AttemptOverviewBlock } from "./AttemptOverviewBlock"
import { renderWithProviders } from "../../test/renderWithProviders"
import { formatDateTime } from "../../utils/date"

describe("AttemptOverviewBlock 交卷時間（#551）", () => {
  it("經 date.ts 格式化，不再是 toLocaleString 的上午／下午與秒數", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} />)
    // 預設 fixture：王小明「基本概念測驗」兩次作答，交卷於 2026-04-22T02:12Z、2026-05-02T06:05Z
    await user.click(await screen.findByRole("button", { name: /王小明/ }))
    // 期望值由 formatDateTime 現算，不寫死字面時刻（依執行環境時區換算）
    expect(await screen.findByText(formatDateTime("2026-04-22T02:12:00Z"))).toBeInTheDocument()
    expect(screen.getByText(formatDateTime("2026-05-02T06:05:00Z"))).toBeInTheDocument()
    expect(screen.queryByText(/上午|下午/)).not.toBeInTheDocument()
  })
})
