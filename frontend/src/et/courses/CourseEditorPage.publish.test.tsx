// 本檔自 CourseEditorPage.test.tsx 拆出（#682）：原檔 2344 行，整組跑時檔內測試互相排擠
// 到超過 5 秒 timeout。本檔負責：刪除草稿、發布缺漏紅框、起訖時間選擇器格式。檔頭的 router mock（含 useBlocker）與 helper
// 各檔各自完整一份，不依賴其他檔的執行順序。

import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import dayjs from "dayjs"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// useParams 可變（切換新增 / 編輯模式）；比照 DM `DmEditorPage.test.tsx`
// ——`renderWithProviders` 內建之 MemoryRouter 無法指定 initialEntries。
const { navigateSpy, paramsRef, locationRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
  // 自動存草稿（#335）跨了元件重新掛載——待開啟的項目由 navigate 的 state 帶過去，
  // 故 useLocation 也須可控。
  locationRef: { current: { pathname: "/et/courses/new", state: null } as { pathname: string; state: unknown } },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    // 離開攔截（#631）需要 data router，`renderWithProviders` 內建的是 MemoryRouter
    // ——真的 `useBlocker` 在此會拋錯。以「永不攔截」取代，站內離開的攔截屬 e2e 行為
    //（比照 DM `DmEditorPage.test.tsx` 與 `QuizAnswerPage.test.tsx`）。
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

/** 編輯模式：帶 courseId 路由參數。 */
function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

/** 新增模式：無路由參數。**不可寫成 `renderNewEditor()`**——傳 undefined 會
 *  觸發預設參數而變成編輯模式，是難以察覺的假通過。 */
function renderNewEditor() {
  paramsRef.current = {}
  return renderWithProviders(<EtCourseEditorPage />)
}

/**
 * 預設 fixture 的課程起訖時間為 null；#558 起「儲存並發布」會先在前端擋下（起訖為發布必填），
 * 測發布**之後**流程的測試要先把時間補上。值放在遠未來：起始時間不可早於當下。
 */
function mockScheduledDraft(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get("/api/et/courses/:courseId", ({ params }) =>
      HttpResponse.json({
        course_id: Number(params.courseId),
        course_name: "採血作業訓練",
        description: "課程說明",
        status: "DRAFT",
        open_start_at: "2099-01-01T00:00:00Z",
        open_end_at: "2099-12-31T00:00:00Z",
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [
          { chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] },
          { chapter_id: 12, chapter_name: "第二章", sort_order: 2, version: 0, items: [] },
        ],
        ...overrides,
      }),
    ),
  )
}

beforeEach(() => {
  navigateSpy.mockClear()
  locationRef.current = { pathname: "/et/courses/new", state: null }
})

// ── ET05 關閉與再開課（US11 / #288）──────────────────────────────────────────

/**
 * 以指定狀態與擁有權覆蓋課程詳細——關閉 / 再開課按鈕全由這兩者決定。
 *
 * `pending` 對應後端的 `has_pending_changes`（#631）：有尚未按下「更新」的內容編輯。
 */
function useCourse(
  status: string,
  { isOwner = true, pending = false }: { isOwner?: boolean; pending?: boolean } = {},
) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status,
        open_start_at: "2026-09-01T00:00:00Z",
        open_end_at: "2027-09-30T00:00:00Z",
        require_approval: false,
        version: 5,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: isOwner,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [],
        invitation_code: isOwner ? "01234567" : null,
        has_pending_changes: pending,
      }),
    ),
  )
}

/** `POST /reopen` 的成功回應——內容與本頁無關（欄位由送出的 payload 決定），只需 200。 */
const reopened = {
  course_id: 1,
  status: "PUBLISHED",
  open_start_at: "2027-11-01T01:00:00Z",
  open_end_at: "2027-12-31T09:00:00Z",
  closed_at: null,
  version: 6,
}

/**
 * 以鍵盤填 `DateTimePicker`。
 *
 * ⚠️ 不是點日曆——MUI 的欄位由五個 section 組成（YYYY/MM/DD HH:mm，24 小時制，#564），逐段
 * 接收按鍵並**自動跳下一段**，故 `keys` 一路打完即可（`"202711010900"` = 2027-11-01 09:00）。
 * ⛔ 不要插 `{ArrowRight}` 跳段，會多跳一格、時分錯位而仍組成一個合法日期（看起來只是
 * 「值不對」，很難連到跳段上）。
 *
 * ⚠️ 必須點在 section 上，點外層的 `role="group"` 不會讓任何一段取得焦點，打的字全部
 * 落空而**測試照樣往下跑**。
 */
async function fillDateTime(label: RegExp, keys: string) {
  const field = screen.getAllByLabelText(label).find((el) => el.getAttribute("role") === "group")
  if (!field) throw new Error(`找不到日期時間欄位：${label}`)
  const first = field.querySelector<HTMLElement>(".MuiPickersSectionList-section")
  if (!first) throw new Error(`欄位沒有可輸入的區段：${label}`)
  // ⚠️ 自備 `delay: null` 的 typist，不沿用測試的 `user`。一次填值是 12 個按鍵、兩個
  // 欄位就 24 個，照預設每鍵 await 一輪會讓單條測試逼近 5s 的預設 timeout——實測本檔
  // 最慢的一條在**單檔**跑就已經 4.5s，全套件並行時必爆（2026-09-24）。
  const typist = userEvent.setup({ delay: null })
  await typist.click(first)
  await typist.keyboard(keys)
}

// ── ET05 刪除草稿（#457）──────────────────────────────────────────────────────

describe("ET05 刪除草稿", () => {
  it("草稿顯示「刪除草稿」，且與「儲存並發布」不相鄰（#457）", async () => {
    // ⚠️ 相鄰性也要驗：本專案的 confirm 確認鈕一律主色、不提供危險色，誤點的防線
    // 只剩版面距離——而「刪掉整門課」與「發布」的誤點代價完全不對稱。
    useCourse("DRAFT")
    renderEditor()

    const del = await screen.findByRole("button", { name: "刪除草稿" })
    const publish = screen.getByRole("button", { name: "儲存並發布" })
    expect(del).toBeInTheDocument()
    // DOM 順序：刪除草稿 → 取消 → 儲存草稿 → 儲存並發布，中間隔著兩顆
    const buttons = screen.getAllByRole("button")
    const gap = buttons.indexOf(publish) - buttons.indexOf(del)
    expect(gap).toBeGreaterThanOrEqual(3)
  })

  it.each([
    ["PUBLISHED", "已發布課程的正解是關閉，不是刪除"],
    ["CLOSED", "已關閉課程的正解是再開課，不是刪除"],
  ])("%s 不顯示「刪除草稿」——%s（#457）", async (status) => {
    useCourse(status)
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    expect(screen.queryByRole("button", { name: "刪除草稿" })).not.toBeInTheDocument()
  })

  it("新增模式不顯示「刪除草稿」——課程還沒寫進 DB（#457）", async () => {
    renderNewEditor()
    await screen.findByRole("heading", { name: "新增課程" })
    expect(screen.queryByRole("button", { name: "刪除草稿" })).not.toBeInTheDocument()
  })

  it("非擁有者不顯示「刪除草稿」（#457）", async () => {
    useCourse("DRAFT", { isOwner: false })
    renderEditor()
    await screen.findByText(/檢視模式/)
    expect(screen.queryByRole("button", { name: "刪除草稿" })).not.toBeInTheDocument()
  })

  it("確認後送出 DELETE、提示成功並導回列表（#457）", async () => {
    const user = userEvent.setup()
    let deleted: string | undefined
    server.use(
      http.delete("/api/et/courses/:courseId", ({ params }) => {
        deleted = String(params.courseId)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    useCourse("DRAFT")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "刪除草稿" }))

    // 確認視窗說明連帶範圍與不可逆
    expect(await screen.findByText(/章節、教材、測驗與課後問卷會一併移除/)).toBeInTheDocument()
    expect(screen.getByText(/無法復原/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認刪除" }))

    await waitFor(() => expect(deleted).toBe("1"))
    expect(await screen.findByText("草稿已刪除")).toBeInTheDocument()
    expect(navigateSpy).toHaveBeenCalledWith("/et/courses")
  })

  it("在確認視窗按取消，一次請求都不發出（#457）", async () => {
    // 🔴 二次確認的重點不是「有沒有跳窗」，是**取消時真的什麼都沒發生**。
    const user = userEvent.setup()
    let calls = 0
    server.use(
      http.delete("/api/et/courses/:courseId", () => {
        calls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    useCourse("DRAFT")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "刪除草稿" }))
    await screen.findByRole("button", { name: "確認刪除" })

    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "確認刪除" })).not.toBeInTheDocument(),
    )
    expect(calls).toBe(0)
    expect(navigateSpy).not.toHaveBeenCalled()
  })
})

// ── #558 發布／再開課缺漏：視窗列出全部 → 關閉後標紅框 → 補好即消失 ─────────────────

describe("ET05 發布缺漏：視窗 → 紅框（#558）", () => {
  /**
   * 一門什麼缺漏都有的草稿：第二章是空的、第一章有一個未命名教材與一個配分不足的測驗、
   * 問卷 0 題。測驗的 quiz_id（31）刻意與另一個項目的 item_id 不同，撞號會框錯列。
   */
  const ITEMS = [
    { item_id: 21, item_type: "MATERIAL", title: "", material_id: 501, quiz_id: null, sort_order: 1, version: 0, question_count: null },
    { item_id: 22, item_type: "QUIZ", title: "小考", material_id: null, quiz_id: 31, sort_order: 2, version: 0, question_count: 2 },
  ]

  /** 後端預檢回傳的缺漏——可在測試中途改寫，模擬「補好之後再查」。 */
  function setup(
    backend: { code: string; message: string; target_id: number | null }[],
    overrides: Record<string, unknown> = {},
  ) {
    const state = { backend, puts: 0, checks: 0 }
    mockScheduledDraft({
      chapters: [
        { chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: ITEMS },
        { chapter_id: 12, chapter_name: "第二章", sort_order: 2, version: 0, items: [] },
      ],
      ...overrides,
    })
    server.use(
      http.get("/api/et/courses/:courseId/publish-check", () => {
        state.checks += 1
        return HttpResponse.json({ can_publish: state.backend.length === 0, blockers: state.backend })
      }),
      http.put("/api/et/courses/:courseId", () => {
        state.puts += 1
        return HttpResponse.json({ course_id: 1, version: 1 })
      }),
      http.get("/api/et/courses/:courseId/survey", () =>
        HttpResponse.json({
          survey_id: 500,
          course_id: 1,
          survey_name: "課後滿意度問卷",
          is_active: true,
          version: 0,
          frozen: false,
          responded_count: 0,
          pending_count: 0,
          questions: [],
        }),
      ),
    )
    return state
  }

  const ALL_BACKEND = [
    // 後端讀的是已存檔版本：已存檔的起訖是有值的，這條是「後端若回了也要被前端取代」的情境
    { code: "NO_SCHEDULE", message: "課程起訖時間須填寫完整", target_id: null },
    { code: "CHAPTER_EMPTY", message: "章節至少須有 1 份教材或測驗", target_id: 12 },
    { code: "ITEM_NO_TITLE", message: "教材與測驗須填寫名稱", target_id: 21 },
    { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 31 },
    { code: "SURVEY_NO_QUESTION", message: "課後問卷至少須有 1 題", target_id: null },
    { code: "OBSOLETE_DOC", message: "請先移除已廢止文件之引用", target_id: null },
  ]

  /** 清掉課程名稱 → 按發布 → 回傳開著的缺漏視窗。 */
  async function publishWithEmptyName(user: ReturnType<typeof userEvent.setup>) {
    renderEditor()
    await user.clear(await screen.findByDisplayValue("採血作業訓練"))
    await user.click(screen.getByRole("button", { name: "儲存並發布" }))
    const dialog = await screen.findByRole("dialog", { name: "發布課程" })
    await within(dialog).findByText("請輸入課程名稱")
    return dialog
  }

  async function closeDialog(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) {
    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  }

  it("前端錯誤與後端缺漏合併在同一個視窗，且表單有錯時不存檔（AC 1）", async () => {
    const user = userEvent.setup()
    const state = setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)

    // 前端那一條與後端那幾條同時在視窗裡
    expect(within(dialog).getByText("請輸入課程名稱")).toBeInTheDocument()
    expect(within(dialog).getByText(/章節至少須有 1 份教材或測驗（章節「第二章」）/)).toBeInTheDocument()
    expect(within(dialog).getByText(/請先移除已廢止文件之引用/)).toBeInTheDocument()
    // #592：草稿沒有「停用問卷」可按，發布情境的提示必須指向刪除（正反同一種查法）
    expect(within(dialog).getByText("請為課後問卷新增至少 1 題，或刪除該問卷")).toBeInTheDocument()
    expect(within(dialog).queryByText(/停用該問卷/)).not.toBeInTheDocument()
    expect(state.puts).toBe(0)
    expect(state.checks).toBe(1)
  })

  it("表單上已填好的起訖時間，不會因後端讀到舊值而被列為缺漏（AC 2）", async () => {
    const user = userEvent.setup()
    setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)

    // 正向錨點與反向斷言用同一種查法：同一個視窗內、文字比對
    expect(within(dialog).getByText(/章節至少須有 1 份教材或測驗/)).toBeInTheDocument()
    expect(within(dialog).queryByText(/課程起訖時間須填寫完整/)).not.toBeInTheDocument()
  })

  it("表單上真的沒填起訖時，「須填寫完整」只列一次（AC 2）", async () => {
    const user = userEvent.setup()
    setup(ALL_BACKEND, { open_start_at: null, open_end_at: null })
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "儲存並發布" }))
    const dialog = await screen.findByRole("dialog", { name: "發布課程" })
    await within(dialog).findByText(/章節至少須有 1 份教材或測驗/)

    expect(within(dialog).getAllByText(/課程起訖時間須填寫完整/)).toHaveLength(1)
  })

  it("視窗開著時不標紅框，關閉後各類缺漏框在對應的元素上（AC 3）", async () => {
    const user = userEvent.setup()
    setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)
    // 視窗開著時背景為 aria-hidden，role 查詢要明示 `hidden: true`
    const name = screen.getByRole("textbox", { name: "課程名稱", hidden: true })

    // 視窗開著：背景不先紅一片（同一件事講兩次）
    expect(name).not.toHaveAttribute("aria-invalid", "true")

    await closeDialog(user, dialog)

    expect(name).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByText("請輸入課程名稱")).toBeInTheDocument()
    // 每個說明文字都要落在**它所指的那一列**裡，不只是「畫面上某處有」
    const chapter = screen.getByText("章節至少須有 1 份教材或測驗").closest(".MuiPaper-root") as HTMLElement
    expect(within(chapter).getByRole("button", { name: "刪除章節 第二章" })).toBeInTheDocument()
    const untitled = screen.getByText("教材與測驗須填寫名稱").closest(".MuiPaper-root") as HTMLElement
    expect(within(untitled).getByRole("button", { name: /^刪除項目 / })).toBeInTheDocument()
    expect(within(untitled).queryByRole("button", { name: "刪除項目 小考" })).not.toBeInTheDocument()
    // 測驗缺漏帶的是 quiz_id（31），要框到「小考」那一列
    const quiz = screen.getByText("測驗各題配分總和須等於 100").closest(".MuiPaper-root") as HTMLElement
    expect(within(quiz).getByRole("button", { name: "刪除項目 小考" })).toBeInTheDocument()
    const survey = screen.getByText("課後問卷至少須有 1 題").closest(".MuiPaper-root") as HTMLElement
    expect(within(survey).getByText("課後滿意度問卷")).toBeInTheDocument()
  })

  it("無對應元素的缺漏只列在視窗，關閉後畫面上不出現（AC 4）", async () => {
    const user = userEvent.setup()
    setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)
    expect(within(dialog).getByText(/請先移除已廢止文件之引用/)).toBeInTheDocument()

    await closeDialog(user, dialog)

    // 正向錨點：同一時刻有其他缺漏確實框出來了——證明「沒出現」不是因為整個標示模式沒啟動
    expect(screen.getByText("章節至少須有 1 份教材或測驗")).toBeInTheDocument()
    expect(screen.queryByText(/請先移除已廢止文件之引用/)).not.toBeInTheDocument()
  })

  it("補好的項目紅框即時消失，沒補的留著（AC 5）", async () => {
    const user = userEvent.setup()
    const state = setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)
    await closeDialog(user, dialog)
    const name = screen.getByRole("textbox", { name: "課程名稱" })
    expect(name).toHaveAttribute("aria-invalid", "true")

    // 表單欄位：一輸入就重算
    await user.type(name, "新名稱")
    expect(name).not.toHaveAttribute("aria-invalid", "true")
    expect(screen.queryByText("請輸入課程名稱")).not.toBeInTheDocument()

    // 章節以下：任何一筆寫入後重查預檢。後端此時只剩未命名教材
    state.backend = [{ code: "ITEM_NO_TITLE", message: "教材與測驗須填寫名稱", target_id: 21 }]
    const chapterName = screen.getByRole("textbox", { name: "章節名稱 2" })
    await user.type(chapterName, "（新增教材）")
    await user.tab() // 失焦即送出更名 → invalidate → 預檢重抓

    await waitFor(() => expect(screen.queryByText("章節至少須有 1 份教材或測驗")).not.toBeInTheDocument())
    expect(screen.getByText("教材與測驗須填寫名稱")).toBeInTheDocument()
    // 互動步驟多（發布 → 關視窗 → 打字 → 更名 → 等重查），單跑約 2.4s；2026-10-07 變異檢查
    // 期間在負載下兩度逼近 5s 而逾時。拉長 timeout 而非刪減步驟——每一步都是 AC 5 的一部分
  }, 15000)

  it("刪除測驗題目後，該測驗的紅框也跟著重算（題目不經課程詳細失效，code review MEDIUM）", async () => {
    // 題目的增刪改走 `invalidateQuiz`，不經 `invalidate()`——預檢 key 雖掛在課程詳細下也
    // 不會被連帶失效。拿掉 `invalidateQuiz` 裡那行，這條會紅、其餘全綠
    const user = userEvent.setup()
    const state = setup(ALL_BACKEND)
    server.use(
      http.get("/api/et/quizzes/:quizId", () =>
        HttpResponse.json({
          quiz_id: 31,
          quiz_name: "小考",
          description: null,
          pass_score: 60,
          time_limit_min: null,
          max_retry: 3,
          version: 0,
          points_total: 40,
          answers_visible: true,
          affected_count: 0,
          questions: [
            { question_id: 91, question_type: "SINGLE", stem: "第一題", points: 40, sort_order: 1, version: 0, options: [] },
          ],
        }),
      ),
      http.delete("/api/et/questions/:questionId", () => new HttpResponse(null, { status: 204 })),
    )
    const dialog = await publishWithEmptyName(user)
    await closeDialog(user, dialog)
    expect(screen.getByText("測驗各題配分總和須等於 100")).toBeInTheDocument()

    state.backend = ALL_BACKEND.filter((b) => b.code !== "QUIZ_POINTS")
    await user.click(screen.getByRole("button", { name: "小考" }))
    await user.click(await screen.findByRole("tab", { name: /題庫管理/ }))
    await user.click(await screen.findByRole("button", { name: "刪除第 1 題" }))
    await user.click(await screen.findByRole("button", { name: "刪除" }))

    await waitFor(() => expect(screen.queryByText("測驗各題配分總和須等於 100")).not.toBeInTheDocument())
    // 正向錨點：沒補的那幾條還在（同一種查法）
    expect(screen.getByText("教材與測驗須填寫名稱")).toBeInTheDocument()
  }, 15000)

  it("刪除問卷後，問卷的紅框也跟著重算（問卷 key 與預檢是兄弟，code review MEDIUM）", async () => {
    const user = userEvent.setup()
    const state = setup(ALL_BACKEND)
    const dialog = await publishWithEmptyName(user)
    await closeDialog(user, dialog)
    expect(screen.getByText("課後問卷至少須有 1 題")).toBeInTheDocument()

    state.backend = ALL_BACKEND.filter((b) => b.code !== "SURVEY_NO_QUESTION")
    await user.click(screen.getByRole("button", { name: "刪除問卷" }))
    await user.click(await screen.findByRole("button", { name: "刪除" }))

    await waitFor(() =>
      expect(screen.queryByText("課後問卷至少須有 1 題")).not.toBeInTheDocument(),
    )
    expect(screen.getByText("教材與測驗須填寫名稱")).toBeInTheDocument()
  }, 15000)

  it("儲存草稿不檢核發布必填、不跳視窗；課程名稱仍當場標紅（AC 6）", async () => {
    const user = userEvent.setup()
    const state = setup(ALL_BACKEND, { open_start_at: null, open_end_at: null, audiences: [] })
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")

    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    await waitFor(() => expect(state.puts).toBe(1))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(state.checks).toBe(0)

    await user.clear(screen.getByRole("textbox", { name: "課程名稱" }))
    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("請輸入課程名稱")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(state.puts).toBe(1)
  })

  it("再開課：時間錯誤與後端缺漏同一個視窗，關閉後時間欄位標示（AC 7）", async () => {
    let reopens = 0
    const user = userEvent.setup()
    useCourse("CLOSED")
    server.use(
      http.get("/api/et/courses/:courseId/publish-check", () =>
        HttpResponse.json({
          can_publish: false,
          blockers: [
            { code: "NO_MATERIAL", message: "課程至少須有 1 份教材", target_id: null },
            { code: "NO_TAG", message: "課程至少須設定 1 組受訓對象", target_id: null },
          ],
        }),
      ),
      http.post("/api/et/courses/:courseId/reopen", () => {
        reopens += 1
        return HttpResponse.json(reopened)
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await user.click(await screen.findByRole("button", { name: "確認再開課" }))

    const dialog = await screen.findByRole("dialog", { name: "再開課" })
    expect(await within(dialog).findByText(/課程至少須有 1 份教材/)).toBeInTheDocument()
    expect(within(dialog).getByText("請重新設定課程起始時間")).toBeInTheDocument()
    // 🔴 再開課的前端只判時間——後端回報的「沒有受訓對象」不可被當成「前端判過了」濾掉
    //（code review MEDIUM；發布流程才會由前端自己判受訓對象）
    expect(within(dialog).getByText(/課程至少須設定 1 組受訓對象/)).toBeInTheDocument()
    expect(reopens).toBe(0)

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByText("請重新設定課程起始時間")).toBeInTheDocument()
    // 仍在再開課模式
    expect(screen.getByRole("button", { name: "確認再開課" })).toBeInTheDocument()
  })
})

// ── #564 起訖時間選擇器：YYYY/MM/DD HH:mm、24 小時制、繁中 ───────────────────────

/**
 * ⚠️ 本組的顯示斷言**守的是「格式來源至少留一條」**，不是單獨守 `format` prop：
 * `PICKER_FORMAT` 與 `adapterLocale="zh-tw"` 各自都能產生 `YYYY/MM/DD HH:mm`（2026-10-08
 * 變異檢查：單獨拿掉任一條全綠、兩條都拿掉 14 條紅）。見 `CourseEditorPage.tsx` 的
 * `PICKER_FORMAT` 註解。⛔ 別因「拿掉 format 測試沒紅」就判定 format 是多餘的而刪掉。
 */
describe("ET05 起訖時間選擇器格式（#564）", () => {
  it("載入既有課程時兩個欄位顯示 YYYY/MM/DD HH:mm，不出現 AM／PM（AC 1）", async () => {
    useCourse("DRAFT")
    renderEditor()
    // 預期值依本機時區格式化——fixture 是 UTC，畫面顯示的是瀏覽器時區
    const start = dayjs("2026-09-01T00:00:00Z").format("YYYY/MM/DD HH:mm")
    const end = dayjs("2027-09-30T00:00:00Z").format("YYYY/MM/DD HH:mm")

    expect(await screen.findByDisplayValue(start)).toBeInTheDocument()
    expect(screen.getByDisplayValue(end)).toBeInTheDocument()
    // 反向斷言用同一種查法（display value）；上面兩條是它的正向錨點
    expect(screen.queryByDisplayValue(/AM|PM/)).not.toBeInTheDocument()
  })

  it("下午的時間以 24 小時制輸入與顯示（17:00，不是 05:00 PM）（AC 1）", async () => {
    // 只改 `format` 而漏了 `ampm={false}` 時，時段仍是 12 小時制：打「17」不會成立。
    // 用下午的時間才驗得到——上午的時間在兩種制度下長得一樣
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711011700")

    expect(screen.getByDisplayValue("2027/11/01 17:00")).toBeInTheDocument()
  })

  it("選擇器的文字為繁體中文，不是英文（#564 範圍：adapterLocale）", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")

    // 開啟選擇器的按鈕名稱取自語系（zhTW：「選擇日期…」／enUS：「Choose date…」）
    expect(screen.getAllByRole("button", { name: /^選擇日期/ })).toHaveLength(2)
    expect(screen.queryAllByRole("button", { name: /^Choose date/ })).toHaveLength(0)
  })
})
