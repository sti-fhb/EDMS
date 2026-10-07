import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SurveyResultBlock } from "./SurveyResultBlock"
import { renderWithProviders } from "../../test/renderWithProviders"
import { formatDateTime } from "../../utils/date"

describe("SurveyResultBlock 提交時間（#551）", () => {
  it("經 date.ts 格式化，不再是 toLocaleString 的上午／下午與秒數", async () => {
    const user = userEvent.setup()
    renderWithProviders(<SurveyResultBlock courseId={1} onExport={vi.fn()} />)
    // 填答時間只在「明細」檢視出現，預設是「統計」——不切換的話表格根本不在畫面上，
    // 下面的否定斷言會因此恆真
    await user.click(await screen.findByRole("button", { name: "明細" }))
    // 預設 fixture：王小明於 2026-05-02T07:00:00Z 提交；期望值由 formatDateTime 現算
    expect(await screen.findByText(formatDateTime("2026-05-02T07:00:00Z"))).toBeInTheDocument()
    expect(screen.queryByText(/上午|下午/)).not.toBeInTheDocument()
  })
})
