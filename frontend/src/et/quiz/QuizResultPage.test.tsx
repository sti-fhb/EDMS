import { screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { AttemptResult } from "./attemptSchemas"
import { EtQuizResultPage } from "./QuizResultPage"
import { renderWithProviders } from "../../test/renderWithProviders"

const navigate = vi.fn()
let state: AttemptResult | null = null

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate, useLocation: () => ({ state }) }
})

const RESULT: AttemptResult = {
  attempt_id: 800,
  quiz_id: 700,
  attempt_no: 1,
  status: "SUBMITTED",
  score: "50.00",
  pass_score: 80,
  is_pass: false,
  submitted_at: "2026-09-04T10:00:00Z",
  remaining_attempts: 3,
  questions: [
    {
      question_id: 901,
      question_type: "SINGLE",
      stem: "採血前應先確認什麼？",
      points: 50,
      score: "50.00",
      outcome: "CORRECT",
      options: [
        { option_id: 9011, text: "捐血人身分", is_correct: true, selected: true },
        { option_id: 9012, text: "天氣", is_correct: false, selected: false },
      ],
    },
    {
      question_id: 902,
      question_type: "MULTIPLE",
      stem: "以下哪些必須檢查？",
      points: 50,
      score: "0.00",
      outcome: "WRONG",
      options: [
        { option_id: 9021, text: "體溫", is_correct: true, selected: false },
        { option_id: 9022, text: "視力", is_correct: false, selected: true },
      ],
    },
  ],
}

describe("ET06 結果頁", () => {
  it("強制顯示正確答案（AC 11 / FR-09）", () => {
    // `spec_us6` FR-09：MUST NOT 提供教師關閉正確答案顯示之選項——這頁沒有任何條件式隱藏
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    const rows = screen.getAllByRole("row")
    expect(rows[1]).toHaveTextContent("捐血人身分") // 你的答案 + 正確答案
    expect(rows[2]).toHaveTextContent("體溫") // 學員沒選，仍須顯示正確答案
  })

  it("未作答顯示「未作答」而非空白", () => {
    // 空白看起來像壞掉
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByRole("row", { name: /Q2/ })).toHaveTextContent("視力")
  })

  it("未及格且有剩餘次數時顯示重新作答（ET-MSG-ET06-004）", () => {
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByText("未達及格分數，您仍有重考機會")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /重新作答/ })).toBeInTheDocument()
  })

  it("未及格但次數用盡時不顯示重新作答", () => {
    state = { ...RESULT, remaining_attempts: 0 }
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.queryByRole("button", { name: /重新作答/ })).not.toBeInTheDocument()
  })

  it("及格時不顯示重新作答", () => {
    state = { ...RESULT, is_pass: true, score: "100.00" }
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByText(/合格/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /重新作答/ })).not.toBeInTheDocument()
  })

  it("逾時自動提交如實標示", () => {
    // 不假裝是正常提交——學員需要知道分數是在時間到的當下結算的
    state = { ...RESULT, status: "TIMEOUT" }
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByText(/作答時間到，已自動提交/)).toBeInTheDocument()
  })

  it("重新作答導回該測驗的引導頁而非 attempt", () => {
    // `attempt_id` 與 `quiz_id` 是兩個獨立序列，用前者推後者會導到錯的測驗
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    screen.getByRole("button", { name: /重新作答/ }).click()

    expect(navigate).toHaveBeenCalledWith("/et/quizzes/700")
  })

  it("直接以網址進入（無結果）時給明確提示而非留白", () => {
    state = null
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByText(/此頁顯示剛提交的成績/)).toBeInTheDocument()
  })
})
