import { QueryClient } from "@tanstack/react-query"
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

/** 與 `server.ts` 預設的兩題作答狀態相同，可覆寫剩餘秒數與已存答案（#608）。 */
function attemptState({
  remainingSec = 600,
  selected = {},
}: { remainingSec?: number; selected?: Record<number, number[]> } = {}) {
  return {
    attempt_id: 800,
    quiz_id: 700,
    quiz_name: "基本概念測驗",
    attempt_no: 1,
    status: "IN_PROGRESS",
    pass_score: 80,
    time_limit_min: 10,
    remaining_sec: remainingSec,
    resumed: false,
    questions: [
      {
        question_id: 901,
        question_type: "SINGLE",
        stem: "採血前應先確認什麼？",
        points: 50,
        options: [
          { option_id: 9011, text: "捐血人身分" },
          { option_id: 9012, text: "天氣" },
        ],
        selected_options: selected[901] ?? [],
      },
      {
        question_id: 902,
        question_type: "MULTIPLE",
        stem: "以下哪些必須檢查？",
        points: 50,
        options: [
          { option_id: 9021, text: "體溫" },
          { option_id: 9022, text: "視力" },
        ],
        selected_options: selected[902] ?? [],
      },
    ],
  }
}

/** 記下每一次暫存請求（題目 + 送出的選項）；`respond` 決定回應，預設 204。 */
function recordSaves(respond: (questionId: number, n: number) => Response = () => new HttpResponse(null, { status: 204 })) {
  const saves: { questionId: number; selected: number[] }[] = []
  server.use(
    http.put("/api/et/attempts/:attemptId/answers/:questionId", async ({ request, params }) => {
      const questionId = Number(params.questionId)
      const body = (await request.json()) as { selected_options: number[] }
      saves.push({ questionId, selected: body.selected_options })
      return respond(questionId, saves.filter((s) => s.questionId === questionId).length)
    }),
  )
  return saves
}

const EXPIRED = () =>
  HttpResponse.json({ error_code: "ET_ATTEMPT_005", error_message: "作答時間已到，請提交本次作答" }, { status: 409 })

describe("ET07 答題頁", () => {
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

  it("提交後導向結果頁並帶上閱卷結果；從學習頁進來時以 replace 進入（#549）", async () => {
    // 前面還有一筆（學習頁）→ 本頁 key 不是 "default" → replace：作答完不該能用上一頁回到作答中
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />, undefined, ["/et/courses/7/learn", "/et/attempts/800"])
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByRole("button", { name: "提交" }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/800/result", expect.anything()))
    expect(navigate).toHaveBeenCalledWith(
      "/et/attempts/800/result",
      expect.objectContaining({ replace: true, state: expect.objectContaining({ attempt_id: 800 }) }),
    )
    // 不是第一筆時不帶標記——否則結果頁會以為沒有上一頁而改走 fallback
    const [, options] = navigate.mock.calls.find(([to]) => to === "/et/attempts/800/result")!
    expect(options.state).not.toHaveProperty("__firstEntry")
  })

  it("本頁是工作階段第一筆（直接開網址）時，進結果頁的 state 帶上「第一筆」標記（#549）", async () => {
    // 單一 initialEntry 的 key 為 "default"——等同直接貼網址進來。replace 會換掉這個 key，
    // 不帶標記的話結果頁的返回會以為有上一頁而離站
    const user = userEvent.setup()
    renderWithProviders(<EtQuizAnswerPage />, undefined, ["/et/attempts/800"])
    await screen.findByText("採血前應先確認什麼？")

    await user.click(screen.getByRole("button", { name: "提交" }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/800/result", expect.anything()))
    expect(navigate).toHaveBeenCalledWith(
      "/et/attempts/800/result",
      expect.objectContaining({
        replace: true,
        state: expect.objectContaining({ attempt_id: 800, __firstEntry: true }),
      }),
    )
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

  describe("交卷與續作不遺失、不覆蓋作答（#608）", () => {
    it("時間到後當前題暫存被拒（ET_ATTEMPT_005），仍完成交卷——不卡在無法提交", async () => {
      // 後端剩餘秒數無條件捨去、前端倒數進位，前端判定時間到時後端必已逾時，當前題暫存一定被拒。
      // 中止提交的話，倒數只自動觸發一次、手動按提交又走同一條暫存——學員永遠交不了卷
      recordSaves(() => EXPIRED())
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))
      await user.click(screen.getByRole("button", { name: "提交" }))

      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/800/result", expect.anything()))
    })

    it("對照：暫存因其他原因失敗（500）仍中止提交，不送出缺一題的考卷", async () => {
      const submitted: number[] = []
      server.use(
        http.post("/api/et/attempts/:attemptId/submit", ({ params }) => {
          submitted.push(Number(params.attemptId))
          return HttpResponse.json({})
        }),
      )
      recordSaves(() => new HttpResponse(null, { status: 500 }))
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))
      await user.click(screen.getByRole("button", { name: "提交" }))

      // 正向錨點：錯誤訊息出現了，代表提交流程真的跑過，「沒有提交」不是因為根本沒按到
      expect(await screen.findByText(/伺服器處理失敗/)).toBeInTheDocument()
      expect(submitted).toEqual([])
      expect(navigate).not.toHaveBeenCalled()
    })

    it("倒數剩最後一分鐘時，點選即暫存，不等切題", async () => {
      server.use(http.get("/api/et/attempts/:attemptId", () => HttpResponse.json(attemptState({ remainingSec: 30 }))))
      const saves = recordSaves()
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))

      await waitFor(() => expect(saves).toEqual([{ questionId: 901, selected: [9011] }]))
    })

    it("對照：時間還多時點選不立即暫存（維持切題 / 提交時才送）", async () => {
      const saves = recordSaves()
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(saves).toEqual([])

      // 正向錨點：同一個 recorder 在切題時確實收得到請求
      await user.click(screen.getByRole("button", { name: /第 2 題/ }))
      await waitFor(() => expect(saves).toEqual([{ questionId: 901, selected: [9011] }]))
    })

    it("離開後回來「繼續作答」：顯示伺服器上的已存答案，切題不會把它覆蓋成空白", async () => {
      // 同一個 QueryClient 模擬「離開作答頁、5 分鐘內再回來」——快取仍在
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      const first = renderWithProviders(<EtQuizAnswerPage />, undefined, undefined, queryClient)
      await screen.findByText("採血前應先確認什麼？")
      first.unmount()

      // 離開期間伺服器上的作答已存了 Q1 = 捐血人身分（例如上次切題時的暫存）。
      // 回應先卡住：重抓回來之前，畫面不可拿快取裡的舊資料讓學員作答——那段空窗裡切題，
      // `savedRef` 還是空的，一樣會把看過沒動的題目暫存成空白
      let release!: () => void
      const gate = new Promise<void>((resolve) => {
        release = resolve
      })
      server.use(
        http.get("/api/et/attempts/:attemptId", async () => {
          await gate
          return HttpResponse.json(attemptState({ selected: { 901: [9011] } }))
        }),
      )
      const saves = recordSaves()
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />, undefined, undefined, queryClient)

      expect(await screen.findByRole("progressbar")).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: /第 2 題/ })).not.toBeInTheDocument()
      release()

      await waitFor(() => expect((screen.getByLabelText("捐血人身分") as HTMLInputElement).checked).toBe(true))

      await user.click(screen.getByRole("button", { name: /第 2 題/ }))
      await user.click(await screen.findByLabelText("體溫"))
      await user.click(screen.getByRole("button", { name: /第 1 題/ }))
      // 正向錨點：Q2 的變動確實被暫存了——下面的「沒有空白暫存」不是建立在空集合上
      await waitFor(() => expect(saves).toContainEqual({ questionId: 902, selected: [9021] }))
      expect(saves.filter((s) => s.selected.length === 0)).toEqual([])
      expect((screen.getByLabelText("捐血人身分") as HTMLInputElement).checked).toBe(true)
    })

    it("最後一分鐘同一題連點：暫存依序送出，後一筆等前一筆落地才送", async () => {
      // 並行送出時落地順序不保證——伺服器可能留下較舊的選擇，而 savedRef 記成較新的值，
      // 提交時不補送，學員以畫面上沒有的答案計分
      server.use(http.get("/api/et/attempts/:attemptId", () => HttpResponse.json(attemptState({ remainingSec: 30 }))))
      let releaseFirst!: () => void
      const firstHeld = new Promise<void>((resolve) => {
        releaseFirst = resolve
      })
      const sent: number[][] = []
      server.use(
        http.put("/api/et/attempts/:attemptId/answers/:questionId", async ({ request }) => {
          const { selected_options } = (await request.json()) as { selected_options: number[] }
          sent.push(selected_options)
          if (sent.length === 1) await firstHeld
          return new HttpResponse(null, { status: 204 })
        }),
      )
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))
      await user.click(screen.getByLabelText("天氣"))
      await waitFor(() => expect(sent).toEqual([[9011]]))
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(sent).toEqual([[9011]])

      releaseFirst()
      await waitFor(() => expect(sent).toEqual([[9011], [9012]]))
    })

    it("重抓作答狀態失敗時，可就地重新載入，不必整頁重新整理", async () => {
      let calls = 0
      server.use(
        http.get("/api/et/attempts/:attemptId", () => {
          calls += 1
          return calls === 1
            ? HttpResponse.json({ error_code: "ET_ATTEMPT_001", error_message: "查無作答" }, { status: 404 })
            : HttpResponse.json(attemptState())
        }),
      )
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)

      expect(await screen.findByText("查無作答")).toBeInTheDocument()
      await user.click(screen.getByRole("button", { name: "重新載入" }))

      expect(await screen.findByText("採血前應先確認什麼？")).toBeInTheDocument()
    })

    it("切題時暫存失敗的題目，提交時補送", async () => {
      // 第一次暫存 Q1 失敗（網路閃斷），之後成功
      const saves = recordSaves((questionId, n) =>
        questionId === 901 && n === 1 ? new HttpResponse(null, { status: 500 }) : new HttpResponse(null, { status: 204 }),
      )
      const user = userEvent.setup()
      renderWithProviders(<EtQuizAnswerPage />)
      await screen.findByText("採血前應先確認什麼？")

      await user.click(screen.getByLabelText("捐血人身分"))
      await user.click(screen.getByRole("button", { name: /第 2 題/ }))
      await waitFor(() => expect(saves).toHaveLength(1))

      await user.click(screen.getByRole("button", { name: "提交" }))

      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/et/attempts/800/result", expect.anything()))
      expect(saves.filter((s) => s.questionId === 901)).toEqual([
        { questionId: 901, selected: [9011] },
        { questionId: 901, selected: [9011] },
      ])
    })
  })
})
