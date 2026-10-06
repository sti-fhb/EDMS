import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { BlockerDialog } from "./BlockerDialog"

const PROPS = {
  title: "再開課",
  message: "課程目前不符發布條件，無法再開課。",
  blockers: [{ code: "NO_MATERIAL", message: "課程至少須有 1 份教材", target_id: null }],
  names: { quiz: {}, chapter: {}, itemChapter: {} },
  onClose: () => {},
}

describe("BlockerDialog（#509）", () => {
  it("顯示標題、說明與缺漏清單", () => {
    render(<BlockerDialog {...PROPS} />)

    const dialog = screen.getByRole("dialog", { name: "再開課" })
    expect(within(dialog).getByText("課程目前不符發布條件，無法再開課。")).toBeInTheDocument()
    expect(within(dialog).getByText("課程至少須有 1 份教材")).toBeInTheDocument()
  })

  it("只有一顆「關閉」——請求已經失敗，視窗是事後告知，不是再問一次", () => {
    render(<BlockerDialog {...PROPS} />)

    const buttons = within(screen.getByRole("dialog")).getAllByRole("button")
    expect(buttons.map((b) => b.textContent)).toEqual(["關閉"])
  })

  it("按「關閉」呼叫 onClose", async () => {
    const onClose = vi.fn()
    render(<BlockerDialog {...PROPS} onClose={onClose} />)

    await userEvent.click(screen.getByRole("button", { name: "關閉" }))

    expect(onClose).toHaveBeenCalledOnce()
  })
})
