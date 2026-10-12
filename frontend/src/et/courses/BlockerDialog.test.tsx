import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { BlockerDialog } from "./BlockerDialog"

const PROPS = {
  title: "再開課",
  message: "課程目前不符發布條件，無法再開課。",
  blockers: [{ code: "NO_MATERIAL", message: "課程至少須有 1 份教材", target_id: null }],
  names: { quiz: {}, chapter: {}, itemChapter: {} },
  context: "reopen" as const,
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

  it("問卷無題目時，再開課情境的導引為停用問卷——已關閉課程的問卷不能刪（#592）", () => {
    const survey = [{ code: "SURVEY_NO_QUESTION", message: "課後問卷至少須有 1 題", target_id: null }]
    render(<BlockerDialog {...PROPS} blockers={survey} />)
    expect(screen.getByText("請為課後問卷新增至少 1 題，或停用該問卷")).toBeInTheDocument()
    expect(screen.queryByText(/刪除該問卷/)).not.toBeInTheDocument()
  })

  it("按「關閉」呼叫 onClose", async () => {
    const onClose = vi.fn()
    render(<BlockerDialog {...PROPS} onClose={onClose} />)

    await userEvent.click(screen.getByRole("button", { name: "關閉" }))

    expect(onClose).toHaveBeenCalledOnce()
  })
})
