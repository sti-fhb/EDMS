// #767 A1：已有待生效的重測要求時，重測視窗對「僅儲存」的說明要依儲存路徑而定。
//
// 只有測驗設定那一支會依本次選擇覆寫重測旗標（`quiz/service.py`）；改題 / 刪題的「僅儲存」
// 意思是「這一次不另外要求」。原本兩條路徑講同一句「會把它一併取消」，改題時那句是假的。
// 元件本身的文案分流見 `RequireRetestDialog.test.tsx`，本檔只驗頁面接線。

import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ courseId: "1" }),
    useLocation: () => ({ pathname: "/et/courses/1", state: null }),
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

const question = (id: number, stem: string) => ({
  question_id: id,
  question_type: "SINGLE",
  stem,
  points: 50,
  sort_order: id,
  version: 0,
  options: [
    { option_id: id * 10 + 1, option_text: "甲", is_correct: true, sort_order: 1 },
    { option_id: id * 10 + 2, option_text: "乙", is_correct: false, sort_order: 2 },
  ],
})

beforeEach(() => {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status: "PUBLISHED",
        open_start_at: "2026-01-01T00:00:00Z",
        open_end_at: "2099-12-31T00:00:00Z",
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        is_closed: false,
        has_pending_changes: true,
        audiences: [],
        chapters: [
          {
            chapter_id: 11,
            chapter_name: "第一章",
            sort_order: 1,
            version: 0,
            items: [{ item_id: 401, item_type: "QUIZ", title: "小考", sort_order: 1, material_id: null, quiz_id: 602 }],
          },
        ],
      }),
    ),
    http.get("/api/et/quizzes/602", () =>
      HttpResponse.json({
        quiz_id: 602,
        quiz_name: "小考",
        description: null,
        pass_score: 80,
        time_limit_min: null,
        max_retry: 3,
        version: 0,
        questions: [question(1, "題一"), question(2, "題二")],
        points_total: 100,
        answers_visible: true,
        affected_count: 1,
        require_retest_pending: true,
      }),
    ),
  )
})

async function openQuiz() {
  const user = userEvent.setup()
  renderWithProviders(<EtCourseEditorPage />)
  await user.click(await screen.findByText("小考"))
  return user
}

describe("重測視窗對待生效要求的說明依儲存路徑而定（#767 A1）", () => {
  it("改題時：說明「僅儲存」不會取消，要到測驗設定", async () => {
    const user = await openQuiz()
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "編輯第 1 題" }))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))

    const dialog = await screen.findByRole("dialog", { name: "是否要求學員重新測驗？" })
    expect(dialog).toHaveTextContent("不會取消它")
    expect(dialog).not.toHaveTextContent("會把它一併取消")
  }, 20000)

  it("測驗設定存檔時：說明「僅儲存」會一併取消", async () => {
    const user = await openQuiz()
    const passScore = await screen.findByLabelText(/及格分數/)
    await user.clear(passScore)
    await user.type(passScore, "85")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    const dialog = await screen.findByRole("dialog", { name: "是否要求學員重新測驗？" })
    expect(dialog).toHaveTextContent("會把它一併取消")
    expect(dialog).not.toHaveTextContent("不會取消它")
  }, 20000)
})
