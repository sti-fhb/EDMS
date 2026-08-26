import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { QuizDialog } from "./QuizDialog"
import type { QuizDetail } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const quiz: QuizDetail = {
  quiz_id: 20,
  quiz_name: "基本概念測驗",
  description: "本測驗為第 1 章內容之自我檢核。",
  pass_score: 80,
  time_limit_min: 10,
  max_retry: 3,
  version: 0,
  questions: [
    {
      question_id: 1,
      question_type: "SINGLE",
      stem: "採血前最重要的消毒步驟是？",
      points: 60,
      sort_order: 1,
      version: 0,
      options: [
        { option_id: 1, option_text: "酒精棉片環狀擦拭", is_correct: true, sort_order: 1 },
        { option_id: 2, option_text: "直接下針", is_correct: false, sort_order: 2 },
      ],
    },
  ],
  points_total: 60,
}

function renderDialog(overrides: Partial<Parameters<typeof QuizDialog>[0]> = {}) {
  const handlers = {
    onClose: vi.fn(),
    onSaveSettings: vi.fn(),
    onSaveQuestion: vi.fn(),
    onDeleteQuestion: vi.fn(),
  }
  renderWithProviders(
    <QuizDialog open loading={false} readOnly={false} quiz={quiz} error={null} {...handlers} {...overrides} />,
  )
  return handlers
}

describe("測驗編輯視窗", () => {
  it("設定分頁載入既有值", async () => {
    renderDialog()
    expect(await screen.findByDisplayValue("基本概念測驗")).toBeInTheDocument()
    expect(screen.getByDisplayValue("80")).toBeInTheDocument()
    expect(screen.getByDisplayValue("10")).toBeInTheDocument()
    expect(screen.getByDisplayValue("本測驗為第 1 章內容之自我檢核。")).toBeInTheDocument()
  })

  it("時間限制留空時送出 null 表示不限時", async () => {
    const user = userEvent.setup()
    const { onSaveSettings } = renderDialog()
    await user.clear(await screen.findByDisplayValue("10"))
    await user.click(screen.getByRole("button", { name: "儲存設定" }))

    expect(onSaveSettings).toHaveBeenCalledWith(expect.objectContaining({ time_limit_min: null }))
  })

  it("測驗說明留空時送出 null", async () => {
    const user = userEvent.setup()
    const { onSaveSettings } = renderDialog()
    await user.clear(await screen.findByDisplayValue("本測驗為第 1 章內容之自我檢核。"))
    await user.click(screen.getByRole("button", { name: "儲存設定" }))

    expect(onSaveSettings).toHaveBeenCalledWith(expect.objectContaining({ description: null }))
  })

  it("提示題目順序由系統洗牌、教師不設定", async () => {
    renderDialog()
    expect(await screen.findByText(/題目順序由系統內建洗牌/)).toBeInTheDocument()
  })

  it("題庫分頁顯示配分總和且未達 100 時不阻擋", async () => {
    const user = userEvent.setup()
    renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))

    expect(await screen.findByText("配分總和 60 / 100")).toBeInTheDocument()
    expect(screen.getByText(/此處不阻擋儲存/)).toBeInTheDocument()
  })

  it("題目摘要列顯示題型、選項數與配分", async () => {
    const user = userEvent.setup()
    renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))

    expect(await screen.findByText("採血前最重要的消毒步驟是？")).toBeInTheDocument()
    expect(screen.getByText(/2 個選項/)).toBeInTheDocument()
    expect(screen.getByText("60 分")).toBeInTheDocument()
  })

  it("點編輯展開該題之編輯器", async () => {
    const user = userEvent.setup()
    renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "編輯第 1 題" }))

    expect(await screen.findByDisplayValue("酒精棉片環狀擦拭")).toBeInTheDocument()
  })

  it("編輯既有題目時帶著該題 id 回呼", async () => {
    const user = userEvent.setup()
    const { onSaveQuestion } = renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "編輯第 1 題" }))
    await user.click(await screen.findByRole("button", { name: "儲存題目" }))

    expect(onSaveQuestion).toHaveBeenCalledWith(1, expect.objectContaining({ stem: "採血前最重要的消毒步驟是？" }))
  })

  it("新增題目時 id 為 null——由呼叫端據此決定 POST 或 PUT", async () => {
    const user = userEvent.setup()
    const { onSaveQuestion } = renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "新增題目" }))

    const stem = await screen.findByLabelText(/題幹/)
    await user.type(stem, "新題目")
    const optionInputs = screen.getAllByRole("textbox", { name: /選項 \d 文字/ })
    await user.type(optionInputs[0], "甲")
    await user.type(optionInputs[1], "乙")
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    expect(onSaveQuestion).toHaveBeenCalledWith(null, expect.objectContaining({ stem: "新題目" }))
  })

  it("展開一題時停用其他題目的編輯入口", async () => {
    // 一次只編一題——每題各有自己的 VERSION，同時編多題會讓版本衝突難以表達
    const user = userEvent.setup()
    renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "新增題目" }))

    expect(screen.getByRole("button", { name: "新增題目" })).toBeDisabled()
  })

  it("刪除題目時通知呼叫端", async () => {
    const user = userEvent.setup()
    const { onDeleteQuestion } = renderDialog()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "刪除第 1 題" }))

    expect(onDeleteQuestion).toHaveBeenCalledWith(quiz.questions[0])
  })

  it("題庫為空時顯示引導文字", async () => {
    const user = userEvent.setup()
    renderDialog({ quiz: { ...quiz, questions: [], points_total: 0 } })
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))

    expect(await screen.findByText(/尚無題目/)).toBeInTheDocument()
  })

  it("唯讀模式不顯示儲存與編輯入口", async () => {
    const user = userEvent.setup()
    renderDialog({ readOnly: true })
    expect(screen.queryByRole("button", { name: "儲存設定" })).not.toBeInTheDocument()

    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /編輯第/ })).not.toBeInTheDocument()
  })
})
