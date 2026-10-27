// 本檔自 CourseEditorPage.test.tsx 拆出（#682）：原檔 2344 行，整組跑時檔內測試互相排擠
// 到超過 5 秒 timeout。本檔負責：新增模式、新增項目與問卷、教材與測驗視窗、發布結果。檔頭的 router mock（含 useBlocker）與 helper
// 各檔各自完整一份，不依賴其他檔的執行順序。

import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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

describe("ET05 課程編輯頁", () => {
  /**
   * ⚠️ **本條設 15000ms**（#687）。成本來自編輯頁元件樹在本檔**第一次**被載入與編譯
   * ——目前由本條（排在檔內最前面）承擔：單檔、機器閒置實測 2.2 秒，份量相近的後續測試只要
   * 0.5～0.9 秒（2026-10-19）；整組並行時實測 5.2 秒逾時（#682 驗收）。
   *
   * 不靠調整順序解決——換誰排第一，誰就要付這筆成本；日後若有測試插到本條之前，該筆成本
   * 會移到那一條上，屆時 timeout 也要跟著移。⛔ 不調全域 `testTimeout`，理由見
   * 下方 #335 那條的說明；負載下仍紅屬 worker 餓死，不要再往上調。
   */
  it("新增章節對話框支援「儲存並繼續新增」", async () => {
    const user = userEvent.setup()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "新增章節" }))

    const input = await screen.findByLabelText("章節名稱")
    await user.type(input, "第三章")
    await user.click(screen.getByRole("button", { name: "儲存並繼續新增" }))

    // 對話框留著、欄位重設——教師可連續新增多個章節
    await waitFor(() => expect(screen.getByLabelText("章節名稱")).toHaveValue(""))
    expect(screen.getByRole("button", { name: "儲存並繼續新增" })).toBeInTheDocument()
  }, 15000)

  it("新增模式顯示全部基本資料欄位且為空白 / 預設值", async () => {
    renderNewEditor()
    expect(await screen.findByRole("heading", { name: "新增課程" })).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "課程名稱" })).toHaveValue("")
    // 起訖採 DateTimePicker（下拉式選擇器 + 確認 / 取消），非原生 datetime-local。
    // MUI 的 label 會同時出現在 <label> 與 fieldset <legend>，故以 role + 精確名稱查。
    // 起訖採 DateTimePicker（下拉式選擇器 + 確認 / 取消），非原生 datetime-local。
    // 它渲染為多層帶 label 的容器（無 role、無 value），逐一斷言「存在且空白」意義不大；
    // 「未填即送出 null」改由下方「一次送出」測試以行為驗證。
    expect(screen.getAllByLabelText("課程起始時間").length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText("課程訖止時間").length).toBeGreaterThan(0)
    expect(screen.getByRole("textbox", { name: "課程描述" })).toHaveValue("")
    expect(screen.getByLabelText("本課程需線下核可")).not.toBeChecked()
    expect(screen.getByLabelText("狀態")).toHaveValue("草稿")
  })

  /**
   * ⚠️ **本條須設 15000ms**（drive-by，#442 順手補）。它做了十幾次 `userEvent` 互動
   * ——打課程名稱、新增章節、填章節名、儲存、新增項目、選教材、填名稱、建立、等
   * navigate——預設的 5000ms 不夠，**在零負載的閒置機器上也會三次紅一次**（2026-09-29
   * 實測：還原成 main 的程式碼連跑三次，1 紅 2 綠，當下 node 行程數 0～1）。
   *
   * 同檔其他份量相近的測試都設了 15000，就這條漏了。
   *
   * ## ⛔ 15000 只修掉「閒置時也會紅」，**負載一來照樣紅**
   *
   * 同日實測：6～9 個 node 行程時，這條要跑 15～16 秒，三次紅兩次。那已經是
   * `.claude/rules/sti-testing.md`「前端假紅判定」講的 worker 餓死，**不可以再往上調**
   * ——調了只是遮症狀，而且真正卡住的測試會更晚才失敗。
   *
   * 兩者的分界：零負載下紅 = 這條真的需要那麼久（本次修的）；有負載才紅 = 排不到 CPU
   * （調 timeout 無效，依該規則逐步判定為假紅）。
   */
  it("新增模式可直接按「新增項目」：自動存草稿後導向編輯頁並帶出待開啟的項目（#335）", async () => {
    const user = userEvent.setup()
    const captured: { body?: { course_name: string; chapters: string[] } } = {}
    server.use(
      http.post("/api/et/courses", async ({ request }) => {
        captured.body = (await request.json()) as NonNullable<typeof captured.body>
        return HttpResponse.json({ course_id: 77, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "自動存草稿課程")
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 按鈕不再 disable——按下去就走「存草稿 → 繼續下一步」（比照 Moodle 的 Save and display）
    await user.click(await screen.findByRole("button", { name: "新增項目" }))
    await user.click(await screen.findByRole("menuitem", { name: /教材/ }))
    // #414：名稱在導向**之前**問完，隨 navigate state 一起帶過去
    await user.type(await screen.findByRole("textbox", { name: "教材名稱" }), "採血流程概論")
    await user.click(screen.getByRole("button", { name: "建立" }))

    // 課程與暫存章節一次送出
    await waitFor(() => expect(captured.body?.chapters).toEqual(["第一章"]))
    // 導向編輯頁（replace：返回鍵不該回到已失效的 /new），並把待開啟的項目帶過去
    await waitFor(() =>
      expect(navigateSpy).toHaveBeenCalledWith(
        "/et/courses/77",
        expect.objectContaining({
          replace: true,
          state: { pendingAddItem: { chapterIndex: 0, itemType: "MATERIAL", title: "採血流程概論" } },
        }),
      ),
    )
  }, 15000)

  /**
   * #435：新增模式下「新增問卷」原本是 disabled 的，提示「請先儲存草稿後再新增問卷」——
   * 同一張編輯頁上，章節本地暫存、項目自動存草稿，只有問卷把存檔這個動作推給教師。
   *
   * 形狀照抄 #335 的項目：名稱在導向**之前**於視窗內填完，隨 navigate state 帶過去。
   */
  it("新增模式可直接按「新增問卷」：自動存草稿後導向編輯頁並帶出待建立的問卷（#435）", async () => {
    const user = userEvent.setup()
    const captured: { body?: { course_name: string; chapters: string[] } } = {}
    server.use(
      http.post("/api/et/courses", async ({ request }) => {
        captured.body = (await request.json()) as NonNullable<typeof captured.body>
        return HttpResponse.json({ course_id: 88, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "有問卷的新課程")

    await user.click(await screen.findByRole("button", { name: "新增問卷" }))
    await user.type(await screen.findByRole("textbox", { name: /問卷名稱/ }), "訓後滿意度調查")
    await user.click(screen.getByRole("button", { name: "建立" }))

    await waitFor(() => expect(captured.body?.course_name).toBe("有問卷的新課程"))
    await waitFor(() =>
      expect(navigateSpy).toHaveBeenCalledWith(
        "/et/courses/88",
        expect.objectContaining({
          replace: true,
          state: { pendingAddSurvey: { surveyName: "訓後滿意度調查" } },
        }),
      ),
    )
  }, 15000)

  /**
   * ⚠️ 這條釘的是 #359 的承諾：「取消時什麼都沒發生」。
   *
   * 自動存草稿必須發生在**按下建立之後**，不可提前到開視窗的時候——否則教師開了
   * 視窗又改變主意，課程草稿已經被建出來了，而他以為自己什麼都沒做。
   */
  it("新增模式開了問卷視窗又關掉：課程草稿一次都沒建（#435）", async () => {
    const user = userEvent.setup()
    let created = 0
    server.use(
      http.post("/api/et/courses", () => {
        created += 1
        return HttpResponse.json({ course_id: 89, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "不會被建立的課程")

    await user.click(await screen.findByRole("button", { name: "新增問卷" }))
    await screen.findByRole("textbox", { name: /問卷名稱/ })
    await user.click(screen.getByRole("button", { name: "關閉視窗" }))

    await waitFor(() => expect(created).toBe(0))
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 15000)

  it("課程名稱未填時按「新增問卷」→ 標欄位錯誤、不開視窗（#435）", async () => {
    const user = userEvent.setup()
    let created = 0
    server.use(
      http.post("/api/et/courses", () => {
        created += 1
        return HttpResponse.json({ course_id: 90, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await screen.findByRole("textbox", { name: "課程名稱" })

    await user.click(await screen.findByRole("button", { name: "新增問卷" }))

    // 比照 `handleAddItem`：錯誤要在他打問卷名稱**之前**出現，否則那個錯誤與他剛做的事無關
    expect(await screen.findByText("請輸入課程名稱")).toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: /問卷名稱/ })).not.toBeInTheDocument()
    await waitFor(() => expect(created).toBe(0))
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 15000)

  it("帶 pendingAddSurvey 進編輯頁時自動建立該問卷並開啟視窗（#435 的後半）", async () => {
    let sentName: string | undefined
    let createdOn: number | null = null
    server.use(
      http.get("/api/et/courses/:courseId/survey", () => HttpResponse.json(null)),
      http.post("/api/et/courses/:courseId/survey", async ({ params, request }) => {
        createdOn = Number(params.courseId)
        sentName = ((await request.json()) as { survey_name?: string }).survey_name
        return HttpResponse.json(
          { survey_id: 31, survey_name: "訓後滿意度調查", is_active: true, version: 0, questions: [] },
          { status: 201 },
        )
      }),
    )
    locationRef.current = {
      pathname: "/et/courses/1",
      state: { pendingAddSurvey: { surveyName: "訓後滿意度調查" } },
    }
    renderEditor("1")

    await waitFor(() => expect(createdOn).toBe(1))
    // 名稱在導向之前就問完了，此處必須原樣帶上，否則後端 422
    expect(sentName).toBe("訓後滿意度調查")
    expect(await screen.findByRole("dialog")).toBeInTheDocument()
  }, 15000)

  /**
   * #435 AC 4：導向後重新整理不會再建一個問卷。
   *
   * ⚠️ **本測試的守衛條件與正式環境相反，而那正好讓它更嚴格。** 正式環境有兩道：
   * `navigate(..., { state: null })` 把 state 清掉，以及 `pendingSurveyHandled` ref
   * 擋重入。但測試裡 `useNavigate` 是 spy，location 不會真的改變——`pendingAddSurvey`
   * 始終為真，且 effect 的 deps 含每次 render 都變的 `handleError`，所以它會不斷重跑。
   * 於是**唯一擋住重複建立的就是 ref**，count 若不是 1 就是 ref 失效。
   *
   * 另外斷言清 state 的那次 navigate 有發生——它是正式環境「重新整理安全」的那一半，
   * 在這裡驗不到效果，只驗它有被呼叫。
   */
  it("pendingAddSurvey 只會建立一次，且會清掉 navigate state（#435 AC 4）", async () => {
    let created = 0
    server.use(
      http.get("/api/et/courses/:courseId/survey", () => HttpResponse.json(null)),
      http.post("/api/et/courses/:courseId/survey", () => {
        created += 1
        return HttpResponse.json(
          { survey_id: 32, survey_name: "只建一次", is_active: true, version: 0, questions: [] },
          { status: 201 },
        )
      }),
    )
    locationRef.current = {
      pathname: "/et/courses/1",
      state: { pendingAddSurvey: { surveyName: "只建一次" } },
    }
    renderEditor("1")

    await screen.findByRole("dialog")
    // 建立後 invalidate 會再觸發查詢與 render；等它們都跑完再數
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument())
    await waitFor(() => expect(created).toBe(1))
    expect(created).toBe(1)
    expect(navigateSpy).toHaveBeenCalledWith("/et/courses/1", { replace: true, state: null })
  }, 15000)

  /**
   * #435 AC 5：自動存草稿失敗時不導向，且不留下半建的問卷。
   *
   * 「半建」在這條路徑上的具體樣子是：課程沒建成卻已經送出了建問卷的請求。導向沒發生
   * 就不會走到建立那一步，但那是**推論**——這裡直接數問卷端點被打了幾次。
   */
  it("自動存草稿失敗時不導向、也不送出建立問卷（#435 AC 5）", async () => {
    const user = userEvent.setup()
    let surveyCreated = 0
    server.use(
      http.post("/api/et/courses", () =>
        HttpResponse.json({ error_code: "ET_COURSE_999", error_message: "伺服器錯誤" }, { status: 500 }),
      ),
      http.post("/api/et/courses/:courseId/survey", () => {
        surveyCreated += 1
        return HttpResponse.json({ survey_id: 33 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "存檔會失敗的課程")

    await user.click(await screen.findByRole("button", { name: "新增問卷" }))
    await user.type(await screen.findByRole("textbox", { name: /問卷名稱/ }), "不會被建立的問卷")
    await user.click(screen.getByRole("button", { name: "建立" }))

    expect(await screen.findByText("伺服器錯誤")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
    await waitFor(() => expect(surveyCreated).toBe(0))
  }, 15000)

  it("課程名稱未填時按「新增項目」→ 標欄位錯誤、不建立草稿（#335）", async () => {
    const user = userEvent.setup()
    let created = 0
    server.use(
      http.post("/api/et/courses", () => {
        created += 1
        return HttpResponse.json({ course_id: 78, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await screen.findByRole("textbox", { name: "課程名稱" })
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    await user.click(await screen.findByRole("button", { name: "新增項目" }))
    await user.click(await screen.findByRole("menuitem", { name: /教材/ }))

    expect(await screen.findByText("請輸入課程名稱")).toBeInTheDocument()
    await waitFor(() => expect(created).toBe(0))
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  /**
   * #442：關閉教材視窗的確認文字原本對兩種情形共用同一句，而它們的後果不同。
   *
   * 既有教材已上傳的影片**不會**因為按取消而移除（影片是選檔即上傳，見 `MaterialDialog`
   * 的模組 docstring），但文字宣稱「尚未儲存的變更將不會保留」——教師據此以為自己
   * 取消掉了。新建立的項目則是取消連項目一起刪，影片跟著消失，那句話成立。
   */
  async function openExistingMaterial(videos: { video_id: number; file_name: string }[]) {
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "採血作業訓練",
          description: null,
          require_approval: false,
          audiences: [],
          status: "DRAFT",
          version: 0,
          is_owner: true,
          open_start_at: null,
          open_end_at: null,
          chapters: [
            {
              chapter_id: 11,
              chapter_name: "第一章",
              sort_order: 1,
              version: 0,
              items: [
                { item_id: 401, item_type: "MATERIAL", title: "採血示範", sort_order: 1, material_id: 601, quiz_id: null },
              ],
            },
          ],
        }),
      ),
      http.get("/api/et/materials/601", () =>
        HttpResponse.json({
          material_id: 601,
          material_name: "採血示範",
          description_html: "<p>原本的說明</p>",
          version: 0,
          videos: videos.map((v, i) => ({ ...v, duration_sec: 600, file_size_bytes: 1024, sort_order: i + 1 })),
          docs: [],
        }),
      ),
    )
    const user = userEvent.setup()
    renderEditor("1")
    await user.click(await screen.findByText("採血示範"))
    await screen.findByRole("dialog")
    return user
  }

  it("既有教材含已上傳影片時，取消的確認文字說明影片會留著（#442）", async () => {
    const user = await openExistingMaterial([{ video_id: 1, file_name: "demo.mp4" }])
    // 改個欄位讓 dirty 成立，否則直接關不跳確認
    await user.clear(await screen.findByRole("textbox", { name: "項目標題" }))
    await user.type(screen.getByRole("textbox", { name: "項目標題" }), "改過的名稱")
    await user.click(screen.getByRole("button", { name: "取消" }))

    // 🔴 **比對整句、含語序**（#814 強化）。
    //
    // 原本只有 `/已上傳的影片不在此列/` 這條片段 regex。#814 把影片的例外說明降為
    // 次要樣式（`component="span"` + `display:block`），而那種改動最容易出的錯是
    // **把「確定關閉？」一起吞進次要樣式、或把例外說明調到句首**——語序變了，片段
    // regex 卻照樣通過。
    //
    // ⚠️ 用 `dialog.textContent` 而非 `getByText`：改成 JSX 後同一句會跨元素。
    const dialog = await screen.findByRole("dialog", { name: "放棄變更" })
    expect(dialog.textContent).toContain(
      "尚未儲存的變更將不會保留。已上傳的影片不在此列——它在選擇檔案時就已保存，取消不會移除。確定關閉？",
    )
  }, 15000)

  it("既有教材沒有影片時不提影片——那句話對他不成立（#442）", async () => {
    const user = await openExistingMaterial([])
    await user.clear(await screen.findByRole("textbox", { name: "項目標題" }))
    await user.type(screen.getByRole("textbox", { name: "項目標題" }), "改過的名稱")
    await user.click(screen.getByRole("button", { name: "取消" }))

    // 這一支 #814 不動（三分支只改中間那支），整句比對同時當它的正向錨點。
    const dialog = await screen.findByRole("dialog", { name: "放棄變更" })
    expect(dialog.textContent).toContain("尚未儲存的變更將不會保留，確定關閉？")
    expect(dialog.textContent).not.toContain("已上傳的影片不在此列")
  }, 15000)

  /**
   * #361 的接線：測驗內容有變更、且有人作答過時（#709 起不限已通過），儲存前先問教師是否要求重測。
   *
   * ⚠️ 元件本身的行為（三顆鈕、ESC、文案）在 `RequireRetestDialog.test.tsx`；
   * 這裡測的是**接線**——何時跳窗、決定之後 API 實際收到什麼。
   */
  async function openQuizDialog(affectedCount: number | null) {
    server.use(
      http.post("/api/et/chapters/:chapterId/items", () =>
        HttpResponse.json(
          { item_id: 502, item_type: "QUIZ", title: "", sort_order: 1, material_id: null, quiz_id: 701 },
          { status: 201 },
        ),
      ),
      http.get("/api/et/quizzes/701", () =>
        HttpResponse.json({
          quiz_id: 701,
          quiz_name: "輸血作業概念測驗",
          description: null,
          pass_score: 80,
          time_limit_min: null,
          max_retry: 2,
          version: 0,
          questions: [],
          points_total: 0,
          answers_visible: true,
          affected_count: affectedCount,
        }),
      ),
    )
    locationRef.current = {
      pathname: "/et/courses/1",
      state: { pendingAddItem: { chapterIndex: 0, itemType: "QUIZ", title: "小考" } },
    }
    renderEditor("1")
    await screen.findByRole("dialog")
  }

  it("已有人作答時，儲存測驗設定會先問是否要求重測（而不是直接送出）", async () => {
    const user = userEvent.setup()
    const sent: { body?: { require_retest: boolean } } = {}
    await openQuizDialog(3)
    server.use(
      http.put("/api/et/quizzes/701", async ({ request }) => {
        sent.body = (await request.json()) as NonNullable<typeof sent.body>
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(await screen.findByText("是否要求學員重新測驗？")).toBeInTheDocument()
    // 🔴 尚未決定之前不可送出——否則教師還沒選，學員狀態就已經變了。
    expect(sent.body).toBeUndefined()
  })

  it("選「儲存並要求重測」後，API 收到 require_retest: true", async () => {
    const user = userEvent.setup()
    const sent: { body?: { require_retest: boolean } } = {}
    await openQuizDialog(3)
    server.use(
      http.put("/api/et/quizzes/701", async ({ request }) => {
        sent.body = (await request.json()) as NonNullable<typeof sent.body>
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await user.click(await screen.findByRole("button", { name: "儲存" }))
    await user.click(await screen.findByRole("button", { name: "儲存並要求重測" }))

    await waitFor(() => expect(sent.body?.require_retest).toBe(true))
  })

  it("沒有人作答過時不跳窗，直接送出 require_retest: false", async () => {
    // 新建測驗的常態。多一個對話框只是噪音。
    const user = userEvent.setup()
    const sent: { body?: { require_retest: boolean } } = {}
    await openQuizDialog(0)
    server.use(
      http.put("/api/et/quizzes/701", async ({ request }) => {
        sent.body = (await request.json()) as NonNullable<typeof sent.body>
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await user.click(await screen.findByRole("button", { name: "儲存" }))

    await waitFor(() => expect(sent.body?.require_retest).toBe(false))
    expect(screen.queryByText("是否要求學員重新測驗？")).not.toBeInTheDocument()
  })

  it("帶 pendingAddItem 進編輯頁時自動建立該項目並開啟視窗（#335 的後半）", async () => {
    let addedTo: number | null = null
    let sentTitle: string | undefined
    server.use(
      http.post("/api/et/chapters/:chapterId/items", async ({ params, request }) => {
        addedTo = Number(params.chapterId)
        sentTitle = ((await request.json()) as { title?: string }).title
        return HttpResponse.json(
          { item_id: 501, item_type: "MATERIAL", title: "採血流程概論", sort_order: 1, material_id: 601, quiz_id: null },
          { status: 201 },
        )
      }),
    )
    locationRef.current = {
      pathname: "/et/courses/1",
      state: { pendingAddItem: { chapterIndex: 0, itemType: "MATERIAL", title: "採血流程概論" } },
    }
    renderEditor("1")

    // 章節載入後依 index 取出真正的 chapter_id 再建項目——建立課程的回應只有 course_id
    await waitFor(() => expect(addedTo).not.toBeNull())
    // #414：名稱在導向之前就問完了，此處必須原樣帶上，否則後端 422
    expect(sentTitle).toBe("採血流程概論")
    expect(await screen.findByRole("dialog")).toBeInTheDocument()
  })

  /**
   * #414：新增項目前先取得名稱。
   *
   * ⚠️ 元件本身的行為（欄位、空白驗證、Enter、取消）在 `NewItemDialog.test.tsx`；
   * 此處只驗**接線**——真正要釘住的是「取消時後端一次都沒被呼叫」。
   */
  it("按下新增項目不會立刻建立——名稱確認後才送出（#414）", async () => {
    let created = 0
    let sentTitle: string | undefined
    server.use(
      http.post("/api/et/chapters/:chapterId/items", async ({ request }) => {
        created += 1
        sentTitle = ((await request.json()) as { title?: string }).title
        return HttpResponse.json(
          { item_id: 502, item_type: "QUIZ", title: "小考", sort_order: 1, material_id: null, quiz_id: 602 },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderEditor("1")
    // 每個章節各有一顆「新增項目」，取第一章那顆
    await user.click((await screen.findAllByRole("button", { name: "新增項目" }))[0])
    await user.click(await screen.findByRole("menuitem", { name: /測驗/ }))

    // 名稱還沒填——此時後端不該收到任何東西
    expect(created).toBe(0)

    await user.type(await screen.findByRole("textbox", { name: "測驗名稱" }), "小考")
    await user.click(screen.getByRole("button", { name: "建立" }))

    await waitFor(() => expect(created).toBe(1))
    expect(sentTitle).toBe("小考")
  })

  it("在命名視窗按取消，後端一次都沒被呼叫（#414）", async () => {
    // 🔴 這是本 issue 的核心。舊行為是按下「新增項目」的當下就建了空殼，而清理只掛在
    // 「取消」上——換頁、重新整理、按「儲存草稿」都會把一個沒有名稱的項目留在章節裡。
    let created = 0
    server.use(
      http.post("/api/et/chapters/:chapterId/items", () => {
        created += 1
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderEditor("1")
    await user.click((await screen.findAllByRole("button", { name: "新增項目" }))[0])
    await user.click(await screen.findByRole("menuitem", { name: /教材/ }))
    await user.click(await screen.findByRole("button", { name: "取消" }))

    expect(created).toBe(0)
    expect(screen.queryByRole("textbox", { name: "教材名稱" })).not.toBeInTheDocument()
  })

  it("發布成功後先看到結果，關閉結果視窗才導回列表（#358 第 4 項）", async () => {
    // 🔴 不可在 `onSuccess` 當下導回。`publishResult` 帶著「帶入 N 位學員」與**邀請碼**，
    // 而邀請碼只有這一次會顯示——立刻導回等於把它從畫面上抽掉。
    //
    // 對照組是「儲存草稿」：它 `onSuccess` 就導回（上方有測試），因為沒有結果要看。
    const user = userEvent.setup()
    mockScheduledDraft()
    server.use(
      http.put("/api/et/courses/:courseId", () => HttpResponse.json({ course_id: 1, version: 1 })),
      http.get("/api/et/courses/:courseId/publish-check", () =>
        HttpResponse.json({ can_publish: true, blockers: [] }),
      ),
      http.post("/api/et/courses/:courseId/publish", () =>
        HttpResponse.json({
          course_id: 1,
          status: "PUBLISHED",
          invitation_code: "ABC12345",
          version: 1,
          invited_count: 7,
        }),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "儲存並發布" }))
    await user.click(await screen.findByRole("button", { name: "確認發布" }))

    // 結果仍在畫面上，且**此時還沒導回**
    expect(await screen.findByText(/已依受訓對象帶入 7 位學員/)).toBeInTheDocument()
    expect(screen.getByText("ABC12345")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "關閉" }))

    expect(navigateSpy).toHaveBeenCalledWith("/et/courses")
  })

  it("發布失敗時留在編輯頁，不導回（#358 第 4 項）", async () => {
    // 失敗會改設 `blockers` 讓教師就地補缺漏；導回列表等於要他自己找回那門課。
    const user = userEvent.setup()
    mockScheduledDraft()
    server.use(
      http.put("/api/et/courses/:courseId", () => HttpResponse.json({ course_id: 1, version: 1 })),
      http.get("/api/et/courses/:courseId/publish-check", () =>
        HttpResponse.json({
          can_publish: false,
          blockers: [{ code: "CHAPTER_EMPTY", message: "章節至少須有 1 份教材或測驗", target_id: 12 }],
        }),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "儲存並發布" }))

    // 🔴 `CHAPTER_EMPTY` 的 `target_id` 是 **chapter_id**（fixture 的 12 = 第二章），
    // 不是 quiz_id。原本兩個對話框都一律查 `quizNames`——撞號時會標成某個不相干的
    // 測驗、不撞號時名稱整個消失，而後端帶 `target_id` 的唯一理由就是「指出是哪一個」。
    expect(await screen.findByText(/章節至少須有 1 份教材或測驗（章節「第二章」）/)).toBeInTheDocument()
    // 「去哪裡修」的第二行提示也要有——`BLOCKER_HINT` 原本沒有這個鍵
    expect(screen.getByText(/請於該章節新增教材或測驗/)).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()

    // #558：有缺漏時只有「關閉」，沒有按不下去的「確認發布」
    await user.click(screen.getByRole("button", { name: "關閉" }))

    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it("未命名項目的缺漏標的是所屬章節，不是項目自己（#384）", async () => {
    // 🔴 `ITEM_NO_TITLE` 的 `target_id` 是 **item_id**，而那個項目**依定義沒有名字**。
    // 若照直覺去查一份 item_id → 項目名稱的對照表，會永遠落空、永遠退回裸訊息，
    // 教師看不出是哪一個——後端帶 `target_id` 的唯一理由又落空一次（同 #358 第 3 項）。
    // 故改標**它所屬的章節**：名字查得到，而且正好把教師帶到要修的那一段。
    const user = userEvent.setup()
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) =>
        HttpResponse.json({
          course_id: Number(params.courseId),
          course_name: "採血作業訓練",
          description: "課程說明",
          status: "DRAFT",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 0,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [
            { chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] },
            {
              chapter_id: 12,
              chapter_name: "第二章",
              sort_order: 2,
              version: 0,
              items: [
                {
                  item_id: 21,
                  item_type: "MATERIAL",
                  title: "",
                  material_id: 501,
                  quiz_id: null,
                  sort_order: 1,
                  version: 0,
                },
              ],
            },
          ],
        }),
      ),
      http.put("/api/et/courses/:courseId", () => HttpResponse.json({ course_id: 1, version: 1 })),
      http.get("/api/et/courses/:courseId/publish-check", () =>
        HttpResponse.json({
          can_publish: false,
          blockers: [{ code: "ITEM_NO_TITLE", message: "教材與測驗須填寫名稱", target_id: 21 }],
        }),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "儲存並發布" }))

    expect(await screen.findByText(/教材與測驗須填寫名稱（章節「第二章」的項目）/)).toBeInTheDocument()
    expect(screen.getByText(/請開啟該項目並填寫名稱/)).toBeInTheDocument()
  })

  it("「儲存並發布」按鈕呈現但停用（發布屬 #204）", async () => {
    renderNewEditor()
    const publish = await screen.findByRole("button", { name: "儲存並發布" })
    expect(publish).toBeDisabled()
    // 不可先讓它能按：發布檢核之「≥ 1 教材」「配分 = 100」要到 #203 才驗得了，
    // 而發布會觸發標籤自動邀請＋寄信，等於通知全體學員一門空課程。
    expect(screen.getByRole("button", { name: "儲存草稿" })).toBeEnabled()
  })

  it("章節名稱留空時於對話框內顯示錯誤且不關閉", async () => {
    const user = userEvent.setup()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.click(await screen.findByRole("button", { name: "儲存" }))
    expect(await screen.findByText("請輸入章節名稱")).toBeInTheDocument()
  })
})
