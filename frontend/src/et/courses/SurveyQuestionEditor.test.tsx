import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SurveyQuestionEditor } from "./SurveyQuestionEditor"
import { EMPTY_SURVEY_QUESTION, SURVEY_MIN_OPTIONS } from "./surveySchemas"
import type { SurveyQuestionDraft } from "./surveySchemas"

const FILLED: SurveyQuestionDraft = {
  question_type: "SINGLE",
  stem: "您對本課程是否滿意？",
  options: [{ option_text: "滿意" }, { option_text: "不滿意" }],
}

function renderEditor(initial: SurveyQuestionDraft = FILLED) {
  const onSave = vi.fn()
  const onCancel = vi.fn()
  render(<SurveyQuestionEditor initial={initial} onSave={onSave} onCancel={onCancel} />)
  return { onSave, onCancel }
}

describe("問卷題目編輯器：單選題", () => {
  it("載入既有內容", () => {
    renderEditor()
    expect(screen.getByDisplayValue("您對本課程是否滿意？")).toBeInTheDocument()
    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(2)
  })

  it("儲存時把值交給呼叫端", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(onSave).toHaveBeenCalledWith({
      question_type: "SINGLE",
      stem: "您對本課程是否滿意？",
      options: [{ option_text: "滿意" }, { option_text: "不滿意" }],
    })
  })

  it("題幹留空時顯示錯誤且不送出", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor({ ...FILLED, stem: "" })
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(await screen.findByText("請輸入題幹")).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it("選項達下限時刪除鈕停用", () => {
    renderEditor()
    expect(screen.getByRole("button", { name: "刪除選項 1" })).toBeDisabled()
  })

  it("選項無上限——可一直加", async () => {
    // 與測驗題目的 2–6 不同，`data-model` §ET_SURVEY_OPTION 只訂下限
    const user = userEvent.setup()
    renderEditor()
    const addButton = screen.getByRole("button", { name: "新增選項" })
    for (let i = 0; i < 6; i += 1) await user.click(addButton)

    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(2 + 6)
    expect(addButton).toBeEnabled()
  })

  it("新增題目之初始值為單選、兩個空選項", () => {
    renderEditor(EMPTY_SURVEY_QUESTION)
    // MUI 的 select 底層 input 存的是代碼（SINGLE），顯示層才是「單選」——
    // 故驗 combobox 的文字內容而非 display value
    expect(screen.getByRole("combobox", { name: "題型" })).toHaveTextContent("單選")
    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(SURVEY_MIN_OPTIONS)
  })
})

describe("問卷題目編輯器：問答題（#238）", () => {
  const textDraft: SurveyQuestionDraft = { question_type: "TEXT", stem: "有什麼建議？", options: [] }

  it("不顯示選項區", () => {
    renderEditor(textDraft)
    expect(screen.queryByRole("button", { name: "新增選項" })).not.toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: /選項 \d 文字/ })).not.toBeInTheDocument()
  })

  it("說明學員的作答形式與字數上限", () => {
    renderEditor(textDraft)
    expect(screen.getByText(/學員以文字作答，至多 150 字/)).toBeInTheDocument()
  })

  it("儲存時 options 為空陣列", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor(textDraft)
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(onSave).toHaveBeenCalledWith({ question_type: "TEXT", stem: "有什麼建議？", options: [] })
  })
})

describe("問卷題目編輯器：切換題型", () => {
  it("由單選切到問答會真的清空選項，不只是隱藏", async () => {
    // 後端對「問答題帶選項」是明確擋下（ET_SURVEY_008）而非靜默忽略——
    // 只把選項區藏起來但仍送出，教師會拿到一個他看不懂的錯誤
    const user = userEvent.setup()
    const { onSave } = renderEditor()
    await user.click(screen.getByRole("combobox", { name: "題型" }))
    await user.click(screen.getByRole("option", { name: "問答" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(onSave).toHaveBeenCalledWith({
      question_type: "TEXT",
      stem: "您對本課程是否滿意？",
      options: [],
    })
  })

  it("由問答切回單選會補回兩個空選項", async () => {
    const user = userEvent.setup()
    renderEditor({ question_type: "TEXT", stem: "有什麼建議？", options: [] })
    await user.click(screen.getByRole("combobox", { name: "題型" }))
    await user.click(screen.getByRole("option", { name: "單選" }))

    // 補回空欄而非留 0 個——留 0 個會讓教師一按儲存就被擋，且不知道要做什麼
    expect(screen.getAllByRole("textbox", { name: /選項 \d 文字/ })).toHaveLength(SURVEY_MIN_OPTIONS)
  })

  it("切回單選後未填選項會被擋下", async () => {
    const user = userEvent.setup()
    const { onSave } = renderEditor({ question_type: "TEXT", stem: "有什麼建議？", options: [] })
    await user.click(screen.getByRole("combobox", { name: "題型" }))
    await user.click(screen.getByRole("option", { name: "單選" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(await screen.findByText("選項文字不得為空白")).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })
})
