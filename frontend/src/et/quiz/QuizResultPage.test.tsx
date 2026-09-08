import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import type { AttemptResult } from "./attemptSchemas"
import { EtQuizResultPage } from "./QuizResultPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
let state: AttemptResult | null = null

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigate,
    useLocation: () => ({ state }),
    useParams: () => ({ attemptId: "800" }),
  }
})

const RESULT: AttemptResult = {
  attempt_id: 800,
  quiz_id: 700,
  course_id: 7,
  attempt_no: 1,
  status: "SUBMITTED",
  score: "50.00",
  points_total: 100,
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
  it("表格本身不顯示題幹——題目在點開之後才出現", () => {
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.queryByText("採血前應先確認什麼？")).not.toBeInTheDocument()
    expect(screen.queryByText("以下哪些必須檢查？")).not.toBeInTheDocument()
  })

  it("點某一列開啟檢討視窗，內含完整題目與全部選項", async () => {
    // wireframe：「點任一列檢視題目與選項，複習檢討」
    state = RESULT
    const user = userEvent.setup()
    renderWithProviders(<EtQuizResultPage />)

    await user.click(screen.getByRole("row", { name: /Q2/ }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("以下哪些必須檢查？")
    // 學員沒選「體溫」（正確答案），視窗中仍須看得到它
    expect(dialog).toHaveTextContent("體溫")
    expect(dialog).toHaveTextContent("視力")
  })

  it("選項以三種狀態標示：選對 / 選錯 / 漏選", async () => {
    // 「你的答案 A,B ／ 正確答案 A,B,E」要讀者自己做集合減法；逐項標示才一眼看得出差在哪
    state = RESULT
    const user = userEvent.setup()
    renderWithProviders(<EtQuizResultPage />)

    await user.click(screen.getByRole("row", { name: /Q2/ }))

    // 狀態由 icon 承載（色條單獨存在對色覺障礙者不可靠），以 icon 的 aria-label 驗
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByLabelText("漏選")).toBeInTheDocument() // 體溫：對但沒選
    expect(within(dialog).getByLabelText("選錯")).toBeInTheDocument() // 視力：選了但錯
    expect(within(dialog).queryByLabelText("答對")).not.toBeInTheDocument() // Q2 全錯
  })

  it("沒有文字標籤時仍給得出圖例", async () => {
    // ⚠ 的語意是「漏選」不是「警告」——icon 不自明，拿掉標籤就必須有圖例
    state = RESULT
    const user = userEvent.setup()
    renderWithProviders(<EtQuizResultPage />)

    await user.click(screen.getByRole("row", { name: /Q1/ }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("答對")
    expect(dialog).toHaveTextContent("選錯")
    expect(dialog).toHaveTextContent("漏選")
  })

  it("鍵盤使用者也進得去檢討視窗", async () => {
    // `<tr>` 本身不可聚焦——整列可點只服務滑鼠，需要一顆真的按鈕
    state = RESULT
    const user = userEvent.setup()
    renderWithProviders(<EtQuizResultPage />)

    await user.click(screen.getByRole("button", { name: "檢視第 1 題" }))

    expect(await screen.findByRole("dialog")).toHaveTextContent("採血前應先確認什麼？")
  })

  it("檢討視窗顯示本題得分，且不重複列出你的答案／正確答案", async () => {
    // 逐項標示就是為了取代那兩串文字；兩個都留著等於同一件事講兩遍
    state = RESULT
    const user = userEvent.setup()
    renderWithProviders(<EtQuizResultPage />)

    await user.click(screen.getByRole("row", { name: /Q2/ }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("本題得分 0.00 / 50")
    expect(dialog).not.toHaveTextContent("你的答案：")
    expect(dialog).not.toHaveTextContent("正確答案：")
  })

  it("強制顯示正確答案（AC 11 / FR-09）", () => {
    // `spec_us6` FR-09：MUST NOT 提供教師關閉正確答案顯示之選項——這頁沒有任何條件式隱藏
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    // 表格摘要就給正確答案，不必點開視窗才看得到
    expect(screen.getByRole("row", { name: /Q1/ })).toHaveTextContent("捐血人身分") // 你的答案 + 正確答案
    expect(screen.getByRole("row", { name: /Q2/ })).toHaveTextContent("體溫") // 學員沒選，仍須顯示正確答案
  })

  it("未作答顯示「未作答」而非空白", () => {
    // 空白看起來像壞掉
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByRole("row", { name: /Q2/ })).toHaveTextContent("視力")
  })

  it("未及格且有剩餘次數時提示可重考（ET-MSG-ET06-004）", () => {
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.getByText("未達及格分數，您仍有重考機會")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /回課程重新作答/ })).toBeInTheDocument()
  })

  it("未及格但次數用盡時不提重考", () => {
    state = { ...RESULT, remaining_attempts: 0 }
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.queryByText("未達及格分數，您仍有重考機會")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "返回課程" })).toBeInTheDocument()
  })

  it("成績區只給一個去處——返回課程", () => {
    // 兩顆意思相近的返回鍵（返回課程 / 回到我的課程）只是讓人多想一次該按哪個
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    expect(screen.queryByRole("button", { name: /回到我的課程/ })).not.toBeInTheDocument()
  })

  it("及格時不提重考", () => {
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

  it("重考導回該課程的學習頁——重考入口只有測驗面板一個", () => {
    // 從結果頁直接開新 attempt 會跳過作答注意事項，且誤觸就吃掉一次次數
    state = RESULT
    renderWithProviders(<EtQuizResultPage />)

    screen.getByRole("button", { name: /回課程重新作答/ }).click()

    expect(navigate).toHaveBeenCalledWith("/et/courses/7/learn")
  })

  it("直接以網址進入（重新整理 / 複習）時改由 API 取回成績", async () => {
    // 這頁同時是引導頁「查看上次作答明細」的落點；沒有 router state 不能再是死路
    state = null
    renderWithProviders(<EtQuizResultPage />)

    expect(await screen.findByText(/50\.00 \/ 100 分/)).toBeInTheDocument()
    expect(screen.getByRole("row", { name: /Q1/ })).toBeInTheDocument()
  })

  it("查無該筆作答時顯示錯誤而非空白頁", async () => {
    state = null
    server.use(
      http.get("/api/et/attempts/:attemptId/result", () =>
        HttpResponse.json({ error_code: "ET_ATTEMPT_001", error_message: "查無此測驗" }, { status: 404 }),
      ),
    )
    renderWithProviders(<EtQuizResultPage />)

    expect(await screen.findByText("查無此測驗")).toBeInTheDocument()
  })
})
