import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtQuizAnswerPage } from "./QuizAnswerPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ attemptId: "800" }) }
})

/** jsdom 的 `document.hidden` 是唯讀 getter，只能覆寫屬性描述子。 */
function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden })
}

function hideTab() {
  setHidden(true)
  document.dispatchEvent(new Event("visibilitychange"))
}

beforeEach(() => {
  navigate.mockReset()
  setHidden(false)
})

describe("ET06 答題頁", () => {
  it("依快照順序呈現題目，且**不含正確答案**", async () => {
    // 正確答案存在於快照，但作答中送出去等於印在網頁原始碼上——洗牌設計會完全失效
    const { container } = renderWithProviders(<EtQuizAnswerPage />)

    expect(await screen.findByText("採血前應先確認什麼？")).toBeInTheDocument()
    expect(container.innerHTML).not.toContain("is_correct")
  })

  it("單選題選了 B 之後 A 自動取消", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByLabelText("捐血人身分"))
    await user.click(screen.getByLabelText("天氣"))

    expect((screen.getByLabelText("捐血人身分") as HTMLInputElement).checked).toBe(false)
    expect((screen.getByLabelText("天氣") as HTMLInputElement).checked).toBe(true)
  })

  it("多選題可同時選多個", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("採血前應先確認什麼？")
    await user.click(await screen.findByRole("button", { name: /第 2 題/ }))

    await user.click(await screen.findByLabelText("體溫"))
    await user.click(screen.getByLabelText("視力"))

    expect((screen.getByLabelText("體溫") as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText("視力") as HTMLInputElement).checked).toBe(true)
  })

  it("切換題目時暫存當前作答（AC 5）", async () => {
    const saved: unknown[] = []
    server.use(
      http.put("/api/et/attempts/:attemptId/answers/:questionId", async ({ request, params }) => {
        saved.push({ questionId: Number(params.questionId), body: await request.json() })
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByLabelText("捐血人身分"))
    await user.click(screen.getByRole("button", { name: /第 2 題/ }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0]).toEqual({ questionId: 901, body: { selected_options: [9011] } })
  })

  it("提交前會先把當前題送出去（最後一題不會漏存）", async () => {
    // **最容易漏的一步**：手動測試幾乎都會先切過題目，所以「在最後一題作答後直接按
    // 提交」這條路徑不會被自然走到——而那正是學員最常做的事。
    const saved: number[] = []
    server.use(
      http.put("/api/et/attempts/:attemptId/answers/:questionId", ({ params }) => {
        saved.push(Number(params.questionId))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByLabelText("捐血人身分"))
    await user.click(screen.getByRole("button", { name: "提交" }))

    await waitFor(() => expect(navigate).toHaveBeenCalled())
    expect(saved).toContain(901)
  })

  it("提交後導向結果頁並帶上閱卷結果", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByRole("button", { name: "提交" }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/800/result", expect.anything()))
  })

  it("有時限時顯示倒數", async () => {
    renderWithProviders(<EtQuizAnswerPage />)

    expect(await screen.findByLabelText("剩餘作答時間")).toBeInTheDocument()
  })

  it("不限時不顯示倒數區塊（AC 2）", async () => {
    // `remaining_sec: null` 是「不限時」，**不是 0**——當成 0 會渲染成「時間到」並立刻自動提交
    server.use(
      http.get("/api/et/attempts/:attemptId", () =>
        HttpResponse.json({
          attempt_id: 800,
          quiz_id: 700,
          quiz_name: "測驗",
          attempt_no: 1,
          status: "IN_PROGRESS",
          pass_score: 80,
          time_limit_min: null,
          remaining_sec: null,
          resumed: false,
          questions: [
            {
              question_id: 901,
              question_type: "SINGLE",
              stem: "題目",
              points: 100,
              options: [{ option_id: 9011, text: "A" }],
              selected_options: [],
            },
          ],
        }),
      ),
    )
    renderWithProviders(<EtQuizAnswerPage />)
    await screen.findByText("題目")

    expect(screen.queryByLabelText("剩餘作答時間")).not.toBeInTheDocument()
  })

  it("續作時提示已回到未完成的作答", async () => {
    server.use(
      http.get("/api/et/attempts/:attemptId", () =>
        HttpResponse.json({
          attempt_id: 800,
          quiz_id: 700,
          quiz_name: "測驗",
          attempt_no: 2,
          status: "IN_PROGRESS",
          pass_score: 80,
          time_limit_min: 10,
          remaining_sec: 300,
          resumed: true,
          questions: [
            {
              question_id: 901,
              question_type: "SINGLE",
              stem: "題目",
              points: 100,
              options: [{ option_id: 9011, text: "A" }],
              selected_options: [],
            },
          ],
        }),
      ),
    )
    renderWithProviders(<EtQuizAnswerPage />)

    expect(await screen.findByText(/已回到您未完成的作答/)).toBeInTheDocument()
  })

  describe("離開作答視窗自動提交", () => {
    it("作答中切換分頁即自動提交，並在結果頁說明原因", async () => {
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      hideTab()

      await waitFor(() =>
        expect(navigate).toHaveBeenCalledWith(
          "/et/attempts/800/result",
          expect.objectContaining({ state: expect.objectContaining({ left_window: true }) }),
        ),
      )
    })

    it("切換到並排的另一個視窗也算離開", async () => {
      // 只聽 `visibilitychange` 會漏掉這個——本分頁仍然可見，而「並排開第二個視窗對照
      // 上一次的答案卷」正是這個機制要擋的用法
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      window.dispatchEvent(new Event("blur"))

      await waitFor(() => expect(navigate).toHaveBeenCalled())
    })

    it("分頁「變回可見」不會觸發提交", async () => {
      // `visibilitychange` 兩個方向都會觸發；不判 `document.hidden` 會在切回來時再交一次
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      setHidden(false)
      document.dispatchEvent(new Event("visibilitychange"))

      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(navigate).not.toHaveBeenCalled()
    })

    it("作答前先在注意事項與畫面上告知", async () => {
      // 誤觸的代價是一次作答次數，事前不講等於用規則懲罰不知情的人
      renderWithProviders(<EtQuizAnswerPage />)

      expect(await screen.findByText(/請勿切換視窗或分頁/)).toBeInTheDocument()
    })

    it("已提交的作答再切換分頁不會重送", async () => {
      // 不擋的話「已提交後用上一頁回來」再切個分頁就打一次注定 409 的提交
      server.use(
        http.get("/api/et/attempts/:attemptId", () =>
          HttpResponse.json({
            attempt_id: 800,
            quiz_id: 700,
            quiz_name: "測驗",
            attempt_no: 1,
            status: "SUBMITTED",
            pass_score: 80,
            time_limit_min: 10,
            remaining_sec: 0,
            resumed: false,
            questions: [],
          }),
        ),
      )
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText(/本次作答已提交/)

      hideTab()
      window.dispatchEvent(new Event("blur"))

      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(navigate).not.toHaveBeenCalled()
    })
  })
})
