import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { QuizIntro } from "./attemptSchemas"
import { EtQuizIntroPage } from "./QuizIntroPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ quizId: "700" }) }
})

const BASE: QuizIntro = {
  quiz_id: 700,
  quiz_name: "基本概念測驗",
  description: null,
  question_count: 5,
  pass_score: 80,
  time_limit_min: 10,
  max_retry: 3,
  remaining_attempts: 4,
  can_start: true,
  last_score: null,
  best_score: null,
  is_passed: false,
  in_progress_attempt_id: null,
}

function mockIntro(overrides: Partial<QuizIntro>) {
  server.use(http.get("/api/et/quizzes/:quizId/intro", () => HttpResponse.json({ ...BASE, ...overrides })))
}

beforeEach(() => navigate.mockReset())

describe("ET06 測驗引導頁", () => {
  it("顯示題數、作答時間、及格分數、剩餘次數（AC 1）", async () => {
    mockIntro({})
    renderWithProviders(<EtQuizIntroPage />)

    expect(await screen.findByText("基本概念測驗")).toBeInTheDocument()
    expect(screen.getByText("題數")).toBeInTheDocument()
    expect(screen.getByText("5")).toBeInTheDocument()
    expect(screen.getByText("及格分數")).toBeInTheDocument()
    expect(screen.getByText("剩餘可作答")).toBeInTheDocument()
  })

  it("不限時顯示「不限時」而非 0 分（AC 2）", async () => {
    // `null` 當成 0 會讓學員以為一進去就結束
    mockIntro({ time_limit_min: null })
    renderWithProviders(<EtQuizIntroPage />)

    expect(await screen.findByText("不限時")).toBeInTheDocument()
    expect(screen.queryByText("0")).not.toBeInTheDocument()
  })

  it("次數用盡時禁用按鈕並提示（ET-MSG-ET06-001）", async () => {
    mockIntro({ can_start: false, remaining_attempts: 0 })
    renderWithProviders(<EtQuizIntroPage />)

    expect(await screen.findByText("重考次數已用完，請聯繫教師重置")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /開始作答/ })).toBeDisabled()
  })

  it("有未完成的作答時按鈕改為「繼續作答」", async () => {
    mockIntro({ in_progress_attempt_id: 800 })
    renderWithProviders(<EtQuizIntroPage />)

    expect(await screen.findByRole("button", { name: /繼續作答/ })).toBeInTheDocument()
  })

  it("同時顯示最近一次與最高分", async () => {
    // 只給最近一次會讓重考後考差的學員以為自己退步了；只給最高分則看不出本次表現
    mockIntro({ last_score: "60.00", best_score: "85.00", is_passed: true })
    renderWithProviders(<EtQuizIntroPage />)

    const alert = await screen.findByText(/最近一次成績/)
    expect(alert).toHaveTextContent("60.00")
    expect(alert).toHaveTextContent("85.00")
  })

  it("點開始作答後導向答題頁", async () => {
    mockIntro({})
    const user = userEvent.setup()
    renderWithProviders(<EtQuizIntroPage />)

    await user.click(await screen.findByRole("button", { name: /開始作答/ }))

    expect(navigate).toHaveBeenCalledWith("/et/attempts/800")
  })

  it("次數用完時後端回 409，前端顯示錯誤而非白畫面", async () => {
    mockIntro({})
    server.use(
      http.post("/api/et/quizzes/:quizId/attempts", () =>
        HttpResponse.json(
          { error_code: "ET_ATTEMPT_002", error_message: "重考次數已用完，請聯繫教師重置" },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtQuizIntroPage />)

    await user.click(await screen.findByRole("button", { name: /開始作答/ }))

    expect(await screen.findByText("重考次數已用完，請聯繫教師重置")).toBeInTheDocument()
    expect(navigate).not.toHaveBeenCalled()
  })
})
