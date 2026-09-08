import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { EtSurveyFillPage } from "./SurveyFillPage"
import type { SurveyEntryState, SurveyForm } from "./surveyFillSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ courseId: "1" }) }
})

const QUESTIONS: SurveyForm["questions"] = [
  {
    sq_id: 1,
    question_type: "SINGLE",
    stem: "整體而言，您對本課程的內容安排是否滿意？",
    options: [
      { so_id: 11, option_text: "滿意" },
      { so_id: 12, option_text: "普通" },
    ],
  },
  {
    sq_id: 2,
    question_type: "SINGLE",
    stem: "影片教材的清晰度與長度是否適當？",
    options: [
      { so_id: 21, option_text: "適當" },
      { so_id: 22, option_text: "需改進" },
    ],
  },
  { sq_id: 3, question_type: "TEXT", stem: "其他建議", options: [] },
]

function mockForm(overrides: Partial<SurveyForm> = {}) {
  server.use(
    http.get("/api/et/courses/:courseId/survey/form", () =>
      HttpResponse.json({
        survey_id: 5,
        survey_name: "課後滿意度問卷",
        state: "FILLABLE" satisfies SurveyEntryState,
        submitted_at: null,
        questions: QUESTIONS,
        my_answers: [],
        ...overrides,
      } satisfies SurveyForm),
    ),
  )
}

/** 攔下送出並回傳收到的 payload，供斷言「實際送了什麼」。 */
function captureSubmit(status = 201) {
  const received: { answers: unknown }[] = []
  server.use(
    http.post("/api/et/courses/:courseId/survey/response", async ({ request }) => {
      received.push((await request.json()) as { answers: unknown })
      if (status !== 201) {
        return HttpResponse.json({ error_code: "ET_SURVEY_013", error_message: "您已填寫過此問卷" }, { status })
      }
      return HttpResponse.json({ response_id: 77, submitted_at: "2026-09-08T06:30:00Z" }, { status: 201 })
    }),
  )
  return received
}

async function confirmDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "送出" }))
}

describe("EtSurveyFillPage", () => {
  it("渲染題目、選項與問卷名稱", async () => {
    mockForm()
    renderWithProviders(<EtSurveyFillPage />)

    expect(await screen.findByText("課後滿意度問卷")).toBeInTheDocument()
    expect(screen.getByText(/1\. 整體而言/)).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: "滿意" })).toBeInTheDocument()
    expect(screen.getByText(/3\. 其他建議/)).toBeInTheDocument()
  })

  it("問答題以文字框呈現且不標必填", async () => {
    mockForm()
    renderWithProviders(<EtSurveyFillPage />)

    const textbox = await screen.findByRole("textbox", { name: "其他建議" })
    expect(textbox).toBeInTheDocument()
    // 星號只給單選題——問答題標星號會讓學員以為非填不可（FR-ET-US13-03 明訂選填）。
    expect(screen.getByText(/3\. 其他建議/).textContent).not.toContain("*")
  })

  it("未答單選題就送出時擋下並逐題標示", async () => {
    // ET-MSG-ET05-101。送出鈕**不 disable**：disabled 的按鈕點下去毫無反應，學員不會
    // 知道是哪一題沒填。故一律可點、擋下並提示（同 #255 對鎖定項目的立場）。
    const user = userEvent.setup()
    mockForm()
    const received = captureSubmit()
    renderWithProviders(<EtSurveyFillPage />)

    await user.click(await screen.findByRole("button", { name: /送出問卷/ }))

    expect(await screen.findByText("尚有題目未作答，請完成後再送出")).toBeInTheDocument()
    expect(screen.getAllByText("尚未作答")).toHaveLength(2)
    expect(received).toHaveLength(0)
  })

  it("只有問答題留空時可以送出", async () => {
    // FR-ET-US13-03：問答題 MUST 為選填，留空 MUST NOT 阻擋送出。
    const user = userEvent.setup()
    mockForm()
    const received = captureSubmit()
    renderWithProviders(<EtSurveyFillPage />)

    await user.click(await screen.findByRole("radio", { name: "滿意" }))
    await user.click(screen.getByRole("radio", { name: "適當" }))
    await user.click(screen.getByRole("button", { name: /送出問卷/ }))
    await confirmDialog(user)

    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0].answers).toEqual([
      { sq_id: 1, so_id: 11, answer_text: null },
      { sq_id: 2, so_id: 21, answer_text: null },
    ])
  })

  it("填了問答題則一併送出去除空白的文字", async () => {
    const user = userEvent.setup()
    mockForm()
    const received = captureSubmit()
    renderWithProviders(<EtSurveyFillPage />)

    await user.click(await screen.findByRole("radio", { name: "普通" }))
    await user.click(screen.getByRole("radio", { name: "需改進" }))
    await user.type(screen.getByRole("textbox", { name: "其他建議" }), "  影片可以再短一些  ")
    await user.click(screen.getByRole("button", { name: /送出問卷/ }))
    await confirmDialog(user)

    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0].answers).toEqual([
      { sq_id: 1, so_id: 12, answer_text: null },
      { sq_id: 2, so_id: 22, answer_text: null },
      { sq_id: 3, so_id: null, answer_text: "影片可以再短一些" },
    ])
  })

  it("送出前需二次確認，取消則不送出", async () => {
    // AC 7 明寫「點『送出』**並確認**」。
    const user = userEvent.setup()
    mockForm()
    const received = captureSubmit()
    renderWithProviders(<EtSurveyFillPage />)

    await user.click(await screen.findByRole("radio", { name: "滿意" }))
    await user.click(screen.getByRole("radio", { name: "適當" }))
    await user.click(screen.getByRole("button", { name: /送出問卷/ }))
    await user.click(await screen.findByRole("button", { name: "取消" }))

    expect(received).toHaveLength(0)
  })

  it("送出成功後導回課程頁", async () => {
    const user = userEvent.setup()
    mockForm()
    captureSubmit()
    renderWithProviders(<EtSurveyFillPage />)

    await user.click(await screen.findByRole("radio", { name: "滿意" }))
    await user.click(screen.getByRole("radio", { name: "適當" }))
    await user.click(screen.getByRole("button", { name: /送出問卷/ }))
    await confirmDialog(user)

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/courses/1/learn"))
    expect(await screen.findByText("問卷已送出，感謝您的回饋")).toBeInTheDocument()
  })

  it("字數計數隨輸入更新", async () => {
    const user = userEvent.setup()
    mockForm()
    renderWithProviders(<EtSurveyFillPage />)

    expect(await screen.findByText("0 / 150")).toBeInTheDocument()
    await user.type(screen.getByRole("textbox", { name: "其他建議" }), "很好")

    expect(await screen.findByText("2 / 150")).toBeInTheDocument()
  })

  it("問答題輸入受 150 字上限限制", async () => {
    // FR-ET-US13-02「至多 150 字，超過時 MUST 阻擋」。前端擋是體驗，後端另有 422。
    mockForm()
    renderWithProviders(<EtSurveyFillPage />)

    expect(await screen.findByRole("textbox", { name: "其他建議" })).toHaveAttribute("maxlength", "150")
  })

  describe("唯讀回看（AC 9）", () => {
    it("已送出時呈現自己的作答、無送出鈕", async () => {
      mockForm({
        state: "SUBMITTED",
        submitted_at: "2026-09-08T06:30:00Z",
        my_answers: [
          { sq_id: 1, so_id: 12, answer_text: null },
          { sq_id: 2, so_id: 21, answer_text: null },
          { sq_id: 3, so_id: null, answer_text: "希望增加實作演練" },
        ],
      })
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByText(/內容不可修改/)).toBeInTheDocument()
      expect(screen.getByRole("radio", { name: "普通" })).toBeChecked()
      expect(screen.getByRole("radio", { name: "適當" })).toBeChecked()
      expect(screen.getByRole("textbox", { name: "其他建議" })).toHaveValue("希望增加實作演練")
      expect(screen.queryByRole("button", { name: /送出問卷/ })).not.toBeInTheDocument()
    })

    it("選項與文字框皆不可修改", async () => {
      mockForm({
        state: "SUBMITTED",
        submitted_at: "2026-09-08T06:30:00Z",
        my_answers: [{ sq_id: 1, so_id: 11, answer_text: null }],
      })
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByRole("radio", { name: "滿意" })).toBeDisabled()
      expect(screen.getByRole("textbox", { name: "其他建議" })).toBeDisabled()
    })

    it("當時留空的問答題呈現為未填", async () => {
      // 後端 `my_answers` 不含那一題（`_D` 只記錄實際有作答的題目，SA Q1 裁示 A）。
      mockForm({
        state: "SUBMITTED",
        submitted_at: "2026-09-08T06:30:00Z",
        my_answers: [
          { sq_id: 1, so_id: 11, answer_text: null },
          { sq_id: 2, so_id: 21, answer_text: null },
        ],
      })
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByRole("textbox", { name: "其他建議" })).toHaveValue("")
      expect(screen.getByPlaceholderText("（未填）")).toBeInTheDocument()
    })
  })

  describe("課程已關閉（AC 10）", () => {
    it("顯示關閉提示、題目全部不可作答且無送出鈕", async () => {
      mockForm({ state: "COURSE_CLOSED" })
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByText("課程已關閉，無法填寫問卷")).toBeInTheDocument()
      expect(screen.getByRole("radio", { name: "滿意" })).toBeDisabled()
      expect(screen.queryByRole("button", { name: /送出問卷/ })).not.toBeInTheDocument()
    })
  })

  describe("未完課（完課回退後）", () => {
    it("說明尚未完課而非給一個點了會失敗的鈕", async () => {
      mockForm({ state: "HIDDEN" })
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByText(/課程尚未完成/)).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: /送出問卷/ })).not.toBeInTheDocument()
    })
  })

  describe("重複送出", () => {
    it("後端回 409 時不顯示錯誤而是轉為已送出", async () => {
      // 開兩個分頁各按一次送出時，第二次的 409 是**正確結果**——他的問卷確實已經送出。
      // 顯示紅色錯誤會讓他以為失敗。
      const user = userEvent.setup()
      mockForm()
      captureSubmit(409)
      renderWithProviders(<EtSurveyFillPage />)

      await user.click(await screen.findByRole("radio", { name: "滿意" }))
      await user.click(screen.getByRole("radio", { name: "適當" }))
      await user.click(screen.getByRole("button", { name: /送出問卷/ }))
      await confirmDialog(user)

      expect(await screen.findByText("問卷已送出，感謝您的回饋")).toBeInTheDocument()
      expect(screen.queryByText("您已填寫過此問卷")).not.toBeInTheDocument()
    })
  })

  describe("錯誤與邊界", () => {
    it("非在籍者顯示後端訊息", async () => {
      server.use(
        http.get("/api/et/courses/:courseId/survey/form", () =>
          HttpResponse.json({ error_code: "ET_SURVEY_011", error_message: "您尚未加入此課程" }, { status: 403 }),
        ),
      )
      renderWithProviders(<EtSurveyFillPage />)

      expect(await screen.findByText("您尚未加入此課程")).toBeInTheDocument()
    })

    it("返回課程鈕導回 ET05", async () => {
      const user = userEvent.setup()
      mockForm()
      renderWithProviders(<EtSurveyFillPage />)

      await user.click(await screen.findByRole("button", { name: "返回課程" }))

      expect(navigate).toHaveBeenCalledWith("/et/courses/1/learn")
    })
  })
})
