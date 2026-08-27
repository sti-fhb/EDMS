import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { QuestionEditor } from "./QuestionEditor"
import { EMPTY_QUESTION } from "./itemSchemas"
import type { QuestionDraft } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const filled: QuestionDraft = {
  question_type: "SINGLE",
  stem: "採血前最重要的消毒步驟是？",
  points: 20,
  options: [
    { option_text: "以酒精棉片環狀擦拭", is_correct: true },
    { option_text: "直接下針", is_correct: false },
  ],
}

function renderEditor(initial: QuestionDraft = filled) {
  const onSave = vi.fn()
  const onCancel = vi.fn()
  renderWithProviders(<QuestionEditor initial={initial} onSave={onSave} onCancel={onCancel} />)
  return { onSave, onCancel }
}

describe("題目編輯器", () => {
  it("載入既有題目之內容", () => {
    renderEditor()
    expect(screen.getByDisplayValue("採血前最重要的消毒步驟是？")).toBeInTheDocument()
    expect(screen.getByDisplayValue("以酒精棉片環狀擦拭")).toBeInTheDocument()
    expect(screen.getByDisplayValue("20")).toBeInTheDocument()
  })

  it("儲存時把值交給呼叫端", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ question_type: "SINGLE", stem: "採血前最重要的消毒步驟是？", points: 20 }),
    )
  })

  it("題幹留空時顯示錯誤且不送出", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor({ ...filled, stem: "" })
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(await screen.findByText("請輸入題幹")).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it("單選題未指定正確答案時顯示對應題型的訊息", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor({
      ...filled,
      options: [
        { option_text: "A", is_correct: false },
        { option_text: "B", is_correct: false },
      ],
    })
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(await screen.findByText("單選題須恰好指定 1 個正確選項")).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it("單選題選取一個正確答案會自動取消其他", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("radio", { name: "選項 2 為正確答案" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    const values = onSave.mock.calls[0][0]
    expect(values.options.map((o: { is_correct: boolean }) => o.is_correct)).toEqual([false, true])
  })

  it("切換為多選題後可同時勾選多個正確答案", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("combobox", { name: "題型" }))
    await user.click(await screen.findByRole("option", { name: "多選" }))
    await user.click(screen.getByRole("checkbox", { name: "選項 2 為正確答案" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    const values = onSave.mock.calls[0][0]
    expect(values.question_type).toBe("MULTIPLE")
    expect(values.options.filter((o: { is_correct: boolean }) => o.is_correct)).toHaveLength(2)
  })

  it("由多選切回單選時只保留一個正確答案", async () => {
    // 否則單選題會帶著兩個正確答案送出，被後端 ET_QUESTION_002 擋下，
    // 而使用者從畫面上看不出是哪裡不對。
    const user = userEvent.setup()
    const { onSave } = renderEditor({
      ...filled,
      question_type: "MULTIPLE",
      options: [
        { option_text: "A", is_correct: true },
        { option_text: "B", is_correct: true },
      ],
    })
    await user.click(screen.getByRole("combobox", { name: "題型" }))
    await user.click(await screen.findByRole("option", { name: "單選" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    const values = onSave.mock.calls[0][0]
    expect(values.options.filter((o: { is_correct: boolean }) => o.is_correct)).toHaveLength(1)
  })

  it("可新增選項至上限 6 個後停用按鈕", async () => {
    const user = userEvent.setup()
    renderEditor()
    const addButton = screen.getByRole("button", { name: "新增選項" })
    for (let i = 0; i < 4; i += 1) await user.click(addButton)

    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(6)
    expect(addButton).toBeDisabled()
  })

  it("刪除唯一的正確選項時自動把正確標記移到第一個", async () => {
    // 不補的話儲存必被擋，而使用者不會預期「刪一個選項導致整題不能存」
    const user = userEvent.setup()
    const { onSave } = renderEditor({
      ...filled,
      options: [
        { option_text: "A", is_correct: true },
        { option_text: "B", is_correct: false },
        { option_text: "C", is_correct: false },
      ],
    })
    await user.click(screen.getByRole("button", { name: "刪除選項 1" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    const values = onSave.mock.calls[0][0]
    expect(values.options).toHaveLength(2)
    expect(values.options[0].is_correct).toBe(true)
  })

  it("選項刪到剩 1 個時儲存被擋", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("button", { name: "刪除選項 2" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(await screen.findByText(/每題選項數須介於 2 至 6 個/)).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it("新增題目之初始值為單選、兩個空選項", () => {
    renderEditor(EMPTY_QUESTION)
    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(2)
    expect(screen.getByRole("radio", { name: "選項 1 為正確答案" })).toBeChecked()
  })

  it("取消時通知呼叫端且不送出", async () => {
    const user = userEvent.setup()
    const { onSave, onCancel } = renderEditor()
    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(onCancel).toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })
})
