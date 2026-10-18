import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { QuizIntro, QuizPreviewQuestion } from "./attemptSchemas"
import { QuizIntroPanel } from "./QuizIntroPanel"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate }
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
  last_attempt_id: null,
  course_closed: false,
  is_preview: false,
  resets: [],
}

function mockIntro(overrides: Partial<QuizIntro>) {
  server.use(http.get("/api/et/quizzes/:quizId/intro", () => HttpResponse.json({ ...BASE, ...overrides })))
}

function mockPreviewQuestions(questions: QuizPreviewQuestion[]) {
  server.use(
    http.get("/api/et/quizzes/:quizId/preview", () =>
      HttpResponse.json({ quiz_id: 700, quiz_name: "基本概念測驗", questions }),
    ),
  )
}

const SINGLE_Q: QuizPreviewQuestion = {
  question_id: 1,
  question_type: "SINGLE",
  stem: "採血前應先確認下列哪一項？",
  points: 50,
  options: [
    { option_id: 11, text: "病人身分" },
    { option_id: 12, text: "採血管顏色" },
  ],
}

beforeEach(() => navigate.mockReset())

describe("ET07 測驗資訊面板", () => {
  it("顯示題數、作答時間、及格分數、剩餘次數（AC 1）", async () => {
    mockIntro({})
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("基本概念測驗")).toBeInTheDocument()
    expect(screen.getByText("題數")).toBeInTheDocument()
    expect(screen.getByText("5")).toBeInTheDocument()
    expect(screen.getByText("及格分數")).toBeInTheDocument()
    expect(screen.getByText("剩餘可作答")).toBeInTheDocument()
  })

  it("不限時顯示「不限時」而非 0 分（AC 2）", async () => {
    // `null` 當成 0 會讓學員以為一進去就結束
    mockIntro({ time_limit_min: null })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("不限時")).toBeInTheDocument()
    expect(screen.queryByText("0")).not.toBeInTheDocument()
  })

  it("次數用盡時禁用按鈕並提示（ET-MSG-ET07-001）", async () => {
    mockIntro({ can_start: false, remaining_attempts: 0 })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("重考次數已用完，請聯繫教師重置")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /開始作答/ })).toBeDisabled()
  })

  it("有歷次紀錄時顯示清單，可回看任一次（不限最近一次）", async () => {
    // #279 只給「上次」的單點入口，那是過渡；學員想回看的往往正是第 1 次
    mockIntro({ last_attempt_id: 800, last_score: "50.00", best_score: "65.00" })
    const user = userEvent.setup()
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("歷次作答紀錄")).toBeInTheDocument()
    await user.click(screen.getByRole("row", { name: /第 1 次/ }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/799/result"))
  })

  describe("輪次分段（#709）", () => {
    it("要求重測後於新一輪前插分隔列，舊輪標「前一輪」且仍可回看", async () => {
      mockIntro({ last_attempt_id: 800, last_score: "50.00", best_score: "50.00", resets: [{ after_attempt_no: 1, kind: "RETEST" as const, executed_at: "2026-10-14T09:00:00Z" }] })
      const user = userEvent.setup()
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByText(/教師要求重測（測驗內容已更新）/)).toBeInTheDocument()
      expect(screen.getByRole("row", { name: /第 1 次/ })).toHaveTextContent("前一輪")
      // 正向對照：新一輪那一列不標前一輪（同一查詢方式）
      expect(screen.getByRole("row", { name: /第 2 次/ })).not.toHaveTextContent("前一輪")
      await user.click(screen.getByRole("row", { name: /第 1 次/ }))
      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/799/result"))
    })

    it("重置重考次數只插分隔列、不標前一輪——舊輪成績仍計入最高分（#709 Q1）", async () => {
      mockIntro({ last_attempt_id: 800, last_score: "50.00", best_score: "65.00", resets: [{ after_attempt_no: 1, kind: "RETRY" as const, executed_at: "2026-10-14T09:00:00Z" }] })
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      // 正向錨點：分隔列確實出現，下面「不標前一輪」才有意義
      expect(await screen.findByText(/重考次數已重置/)).toBeInTheDocument()
      expect(screen.getByRole("row", { name: /第 1 次/ })).not.toHaveTextContent("前一輪")
    })

    it("要求重測後尚未重考：說明結業成績待重新作答，不顯示舊的最高分", async () => {
      mockIntro({
        last_attempt_id: 800,
        last_score: "90.00",
        best_score: null,
        resets: [{ after_attempt_no: 2, kind: "RETEST" as const, executed_at: "2026-10-14T09:00:00Z" }],
      })
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByText(/教師已要求重測，重新作答後才會計算結業成績/)).toBeInTheDocument()
      // 成績橫幅（最近一次＋最高分）不出現——頁面其他處本來就有「最高分」字樣，不能以它為準
      expect(screen.queryByText(/最近一次成績/)).not.toBeInTheDocument()
    })
  })

  it("從未作答時整塊清單不顯示", async () => {
    // 一張空表格會讓學員以為系統把他的紀錄弄丟了
    server.use(http.get("/api/et/quizzes/:quizId/attempts", () => HttpResponse.json([])))
    mockIntro({ last_attempt_id: null })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    await screen.findByRole("button", { name: /開始作答/ })
    expect(screen.queryByText("歷次作答紀錄")).not.toBeInTheDocument()
  })

  it("次數用盡仍可回看歷次（複習）", async () => {
    // 次數用完的學員正是最需要回頭看錯在哪的人；把複習跟著作答一起關掉等於懲罰他考不好
    mockIntro({ can_start: false, remaining_attempts: 0, last_attempt_id: 800 })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("歷次作答紀錄")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /開始作答/ })).toBeDisabled()
  })

  it("課程關閉時的訊息是關閉，不是「次數用完請聯繫教師重置」", async () => {
    // 兩種成因對學員的意義相反：關閉時叫他去找教師重置，是叫他做一件沒有用的事
    mockIntro({ can_start: false, course_closed: true })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("此課程已關閉，無法再開新作答")).toBeInTheDocument()
    expect(screen.queryByText("重考次數已用完，請聯繫教師重置")).not.toBeInTheDocument()
  })

  it("次數用完且課程未關閉時顯示重置提示", async () => {
    mockIntro({ can_start: false, remaining_attempts: 0, course_closed: false })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText("重考次數已用完，請聯繫教師重置")).toBeInTheDocument()
    expect(screen.queryByText("此課程已關閉，無法再開新作答")).not.toBeInTheDocument()
  })

  it("有未完成的作答時告知按下會結算，按鈕仍是「開始作答」而非「繼續作答」（#640）", async () => {
    mockIntro({ in_progress_attempt_id: 800 })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    expect(await screen.findByText(/上次的作答尚未提交/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "開始作答" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /繼續作答/ })).not.toBeInTheDocument()
  })

  it("沒有未完成的作答時不顯示結算提示", async () => {
    mockIntro({})
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    // 正向錨點：面板已渲染完成（同一個查詢方式找得到按鈕）
    expect(await screen.findByRole("button", { name: "開始作答" })).toBeInTheDocument()
    expect(screen.queryByText(/上次的作答尚未提交/)).not.toBeInTheDocument()
  })

  it("開始作答時後端結算了殘留作答 → 帶著成績進結果頁並註明是自動提交（#640）", async () => {
    mockIntro({ in_progress_attempt_id: 800 })
    server.use(
      http.post("/api/et/quizzes/:quizId/attempts", () =>
        HttpResponse.json(
          {
            attempt_id: 800,
            quiz_id: 700,
            course_id: 7,
            attempt_no: 1,
            status: "SUBMITTED",
            score: "50.00",
            points_total: 100,
            pass_score: 80,
            is_pass: false,
            submitted_at: "2026-10-14T02:00:00Z",
            remaining_attempts: 2,
            course_closed: false,
            questions: [],
          },
          { status: 200 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    await user.click(await screen.findByRole("button", { name: "開始作答" }))

    // #549：一樣先釘 ?quiz=，結果頁的返回才會落在這個測驗
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(2))
    expect(navigate.mock.calls[1]).toEqual([
      "/et/attempts/800/result",
      { state: expect.objectContaining({ attempt_id: 800, status: "SUBMITTED", auto_settled: true }) },
    ])
  })

  it("同時顯示最近一次與最高分", async () => {
    // 只給最近一次會讓重考後考差的學員以為自己退步了；只給最高分則看不出本次表現
    mockIntro({ last_score: "60.00", best_score: "85.00", is_passed: true })
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    const alert = await screen.findByText(/最近一次成績/)
    expect(alert).toHaveTextContent("60.00")
    expect(alert).toHaveTextContent("85.00")
  })

  it("點開始作答後導向答題頁", async () => {
    mockIntro({})
    const user = userEvent.setup()
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    await user.click(await screen.findByRole("button", { name: /開始作答/ }))

    // #549：先把學習頁網址釘成帶 ?quiz=（replace），**之後**才進作答頁——結果頁會退回這一筆
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(2))
    expect(navigate.mock.calls[0]).toEqual([{ pathname: "/", search: "?quiz=700", hash: "" }, { replace: true, state: { __firstEntry: true } }])
    expect(navigate.mock.calls[1]).toEqual(["/et/attempts/800"])
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
    renderWithProviders(<QuizIntroPanel quizId={700} />)

    await user.click(await screen.findByRole("button", { name: /開始作答/ }))

    expect(await screen.findByText("重考次數已用完，請聯繫教師重置")).toBeInTheDocument()
    expect(navigate).not.toHaveBeenCalled()
  })

  describe("預覽模式（#486）", () => {
    it("顯示唯讀題目與選項，且選項不可點選", async () => {
      mockIntro({ is_preview: true, can_start: false })
      mockPreviewQuestions([SINGLE_Q])
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByText("採血前應先確認下列哪一項？")).toBeInTheDocument()
      expect(screen.getByText("病人身分")).toBeInTheDocument()
      expect(screen.getByRole("radio", { name: "病人身分" })).toBeDisabled()
    })

    it("不顯示開始作答鈕、剩餘次數與作答注意事項", async () => {
      mockIntro({ is_preview: true, can_start: false })
      mockPreviewQuestions([SINGLE_Q])
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      // ⚠️ 正向錨點必須先到位：`queryBy*` 在資料還沒回來時一律找不到，恆真。
      expect(await screen.findByText("採血前應先確認下列哪一項？")).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: /開始作答|繼續作答/ })).not.toBeInTheDocument()
      expect(screen.queryByText("剩餘可作答")).not.toBeInTheDocument()
      expect(screen.queryByText("作答注意事項")).not.toBeInTheDocument()
    })

    it("不顯示「重考次數已用完」——那對預覽的教師是一句不成立的話", async () => {
      // `can_start=false` 的第三種成因（#486）。少了這條，前端沿用舊的兩分支判斷也會
      // 通過上面兩條，而教師會看到一句叫他去聯繫自己的訊息。
      mockIntro({ is_preview: true, can_start: false, course_closed: false })
      mockPreviewQuestions([SINGLE_Q])
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByText("採血前應先確認下列哪一項？")).toBeInTheDocument()
      expect(screen.queryByText("重考次數已用完，請聯繫教師重置")).not.toBeInTheDocument()
      expect(screen.queryByText("此課程已關閉，無法再開新作答")).not.toBeInTheDocument()
    })

    it("多選題呈現為核取方塊", async () => {
      mockIntro({ is_preview: true, can_start: false })
      mockPreviewQuestions([{ ...SINGLE_Q, question_type: "MULTIPLE" }])
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByRole("checkbox", { name: "病人身分" })).toBeDisabled()
      expect(screen.getByText("多選題")).toBeInTheDocument()
    })

    it("尚未出題時明說學員看不到內容，而不是留白", async () => {
      mockIntro({ is_preview: true, can_start: false, question_count: 0 })
      mockPreviewQuestions([])
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByText(/此測驗尚未新增任何題目/)).toBeInTheDocument()
    })

    it("非預覽時不打預覽端點，照舊顯示開始作答", async () => {
      // 與本組其餘成對：少了它，把 `is_preview` 的判斷寫反也會讓上面五條全綠。
      // 在籍學員打預覽端點會拿到 404，症狀是測驗面板下方多一塊紅色錯誤。
      let previewCalled = false
      mockIntro({})
      server.use(
        http.get("/api/et/quizzes/:quizId/preview", () => {
          previewCalled = true
          return HttpResponse.json({ quiz_id: 700, quiz_name: "基本概念測驗", questions: [] })
        }),
      )
      renderWithProviders(<QuizIntroPanel quizId={700} />)

      expect(await screen.findByRole("button", { name: /開始作答/ })).toBeInTheDocument()
      expect(previewCalled).toBe(false)
    })
  })
})
