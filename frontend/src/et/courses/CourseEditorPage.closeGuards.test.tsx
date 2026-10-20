// #767：關閉視窗或關閉課程時，已經做過的事不可在沒有提示的情況下消失。
//
// ① 新建項目在第一次按底部「儲存」前，已上傳影片或已存題目——關閉視窗不可把整個項目刪掉
// ④ 已發布課程有尚未「更新」的編輯時按「關閉課程」——確認視窗要說這些編輯會被放棄
//
// 檔頭的 router mock 與 helper 比照同目錄其他 `CourseEditorPage.*.test.tsx`，各檔各自完整一份。

import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const { navigateSpy, paramsRef, locationRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
  locationRef: { current: { pathname: "/et/courses/1", state: null } as { pathname: string; state: unknown } },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

function mockCourse(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status: "DRAFT",
        open_start_at: null,
        open_end_at: null,
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        audiences: [],
        chapters: [{ chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] }],
        ...overrides,
      }),
    ),
  )
}

/** 記下對 `DELETE /api/et/items/:id` 的呼叫——①的判準就是「它有沒有被打」。 */
function spyItemDelete() {
  const deleted: number[] = []
  server.use(
    http.delete("/api/et/items/:itemId", ({ params }) => {
      deleted.push(Number(params.itemId))
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return deleted
}

async function createNewItem(user: ReturnType<typeof userEvent.setup>, kind: "教材" | "測驗", name: string) {
  await user.click((await screen.findAllByRole("button", { name: "新增項目" }))[0])
  await user.click(await screen.findByRole("menuitem", { name: new RegExp(kind) }))
  await user.type(await screen.findByRole("textbox", { name: `${kind}名稱` }), name)
  await user.click(screen.getByRole("button", { name: "建立" }))
}

beforeEach(() => {
  navigateSpy.mockClear()
  locationRef.current = { pathname: "/et/courses/1", state: null }
})

describe("① 新建項目關閉時不可吃掉已保存的內容（#767）", () => {
  function mockNewMaterial() {
    let videos: unknown[] = []
    server.use(
      http.post("/api/et/chapters/:chapterId/items", () =>
        HttpResponse.json(
          { item_id: 501, item_type: "MATERIAL", title: "採血示範", sort_order: 1, material_id: 601, quiz_id: null },
          { status: 201 },
        ),
      ),
      http.get("/api/et/materials/601", () =>
        HttpResponse.json({
          material_id: 601,
          material_name: "採血示範",
          description_html: null,
          version: 0,
          videos,
          docs: [],
        }),
      ),
      http.post("/api/et/materials/601/videos", () => {
        const row = { video_id: 1, file_name: "demo.mp4", duration_sec: 600, file_size_bytes: 1024, sort_order: 1 }
        videos = [row]
        return HttpResponse.json(row, { status: 201 })
      }),
    )
  }

  it("新建教材上傳影片後直接取消：不刪除項目", async () => {
    mockCourse()
    mockNewMaterial()
    const deleted = spyItemDelete()
    const user = userEvent.setup()
    renderEditor()
    await createNewItem(user, "教材", "採血示範")

    await user.upload(
      await screen.findByLabelText("選擇影片檔"),
      new File(["x"], "demo.mp4", { type: "video/mp4" }),
    )
    expect(await screen.findByText("demo.mp4")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "取消" }))
    // 取消可能跳確認（若視窗判定有變更）；有的話確定下去，判準只看項目是否被刪
    const ok = screen.queryByRole("button", { name: "確定" })
    if (ok) await user.click(ok)

    await waitFor(() => expect(screen.queryByLabelText("選擇影片檔")).not.toBeInTheDocument())
    expect(deleted).toEqual([])
  }, 15000)

  it("新建教材什麼都沒做就取消：照舊刪除空殼（原行為不變）", async () => {
    mockCourse()
    mockNewMaterial()
    const deleted = spyItemDelete()
    const user = userEvent.setup()
    renderEditor()
    await createNewItem(user, "教材", "採血示範")

    await screen.findByLabelText("選擇影片檔")
    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() => expect(deleted).toEqual([501]))
  }, 15000)

  it("新建測驗存了一題後直接關閉：不刪除項目", async () => {
    let questions: unknown[] = []
    mockCourse()
    server.use(
      http.post("/api/et/chapters/:chapterId/items", () =>
        HttpResponse.json(
          { item_id: 502, item_type: "QUIZ", title: "小考", sort_order: 1, material_id: null, quiz_id: 602 },
          { status: 201 },
        ),
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
          questions,
          points_total: questions.length * 100,
          answers_visible: true,
          affected_count: 0,
          require_retest_pending: false,
        }),
      ),
      http.post("/api/et/quizzes/602/questions", () => {
        const row = {
          question_id: 9001,
          question_type: "SINGLE",
          stem: "題目一",
          points: 100,
          sort_order: 1,
          version: 0,
          options: [
            { option_id: 1, option_text: "甲", is_correct: true, sort_order: 1 },
            { option_id: 2, option_text: "乙", is_correct: false, sort_order: 2 },
          ],
        }
        questions = [row]
        return HttpResponse.json(row, { status: 201 })
      }),
    )
    const deleted = spyItemDelete()
    const user = userEvent.setup()
    renderEditor()
    await createNewItem(user, "測驗", "小考")

    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "新增題目" }))
    await user.type(await screen.findByLabelText(/題幹/), "題目一")
    const points = screen.getByLabelText(/配分/)
    await user.clear(points)
    await user.type(points, "100")
    await user.type(screen.getByLabelText("選項 1 文字"), "甲")
    await user.type(screen.getByLabelText("選項 2 文字"), "乙")
    await user.click(screen.getByLabelText("選項 1 為正確答案"))
    await user.click(screen.getByRole("button", { name: "儲存題目" }))
    expect(await screen.findByText("題目一")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "關閉視窗" }))
    const ok = screen.queryByRole("button", { name: "確定" })
    if (ok) await user.click(ok)

    await waitFor(() => expect(screen.queryByRole("tab", { name: /題庫管理/ })).not.toBeInTheDocument())
    expect(deleted).toEqual([])
  }, 20000)
})

describe("④ 已發布課程有未更新的編輯時關閉課程（#767）", () => {
  const published = {
    status: "PUBLISHED",
    open_start_at: "2026-01-01T00:00:00Z",
    open_end_at: "2099-12-31T00:00:00Z",
    is_closed: false,
  }

  it("有尚未「更新」的編輯：確認視窗說明這些編輯會被放棄", async () => {
    mockCourse({ ...published, has_pending_changes: true })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("尚未按「更新」")
    expect(dialog).toHaveTextContent("關閉後這些編輯不會保留")
  }, 15000)

  it("沒有未更新的編輯：維持原本的確認文字，不提編輯", async () => {
    mockCourse({ ...published, has_pending_changes: false })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("關閉後學員無法加入")
    expect(dialog).not.toHaveTextContent("尚未按「更新」")
  }, 15000)
})
