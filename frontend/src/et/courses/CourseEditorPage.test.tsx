// 本檔自 CourseEditorPage.test.tsx 拆出（#682）：原檔 2344 行，整組跑時檔內測試互相排擠
// 到超過 5 秒 timeout。本檔負責：編輯模式載入、基本資料與受訓對象配對。檔頭的 router mock（含 useBlocker）與 helper
// 各檔各自完整一份，不依賴其他檔的執行順序。

import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor, within } from "@testing-library/react"
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
  it("編輯模式載入既有課程資料與章節", async () => {
    renderEditor()
    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
    expect(await screen.findByDisplayValue("第一章")).toBeInTheDocument()
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()
  })

  it("存檔後重進編輯頁：三個欄位都預帶新值，不被快取舊值鎖住（#578 手測回報）", async () => {
    // 重進時 TanStack Query（staleTime 0）會先**同步**吐出快取裡的舊課程再背景 refetch；
    // 表單初值的一次性 guard（`loadedCourseId !== course.course_id`）若不等 refetch 落定，
    // 就會被舊值填滿並從此鎖住，稍後回來的新值再也寫不進表單——表現為「列表已是新名稱，
    // 點進編輯頁卻還是舊的」。同一個形狀在 DM 編輯頁是 #377。
    //
    // ⚠️ 必須**跨兩次 mount 共用同一個 QueryClient**，否則第二次的快取是空的、必然重抓，
    // 舊值永遠不會出現——這條測試會在修好前後都通過。
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    paramsRef.current = { courseId: "1" }

    const first = renderWithProviders(<EtCourseEditorPage />, undefined, undefined, qc)
    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
    first.unmount()

    // 使用者已存檔並離開；後端自此回新值
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) =>
        HttpResponse.json({
          course_id: Number(params.courseId),
          course_name: "採血作業訓練（已改名）",
          description: "改過的課程說明",
          status: "DRAFT",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 1,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 102, tag_id: 3, label: "國防醫學院三軍總醫院 + 行政人員" }],
          chapters: [{ chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] }],
        }),
      ),
    )

    renderWithProviders(<EtCourseEditorPage />, undefined, undefined, qc)

    // 三個欄位分開驗：手測回報的是課程名稱 / 受訓對象 / 課程描述三項都沒更新
    expect(await screen.findByDisplayValue("採血作業訓練（已改名）")).toBeInTheDocument()
    expect(screen.getByDisplayValue("改過的課程說明")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "第 1 組的單位" })).toHaveValue("國防醫學院三軍總醫院")
    expect(screen.getByRole("combobox", { name: "第 1 組的職位" })).toHaveValue("行政人員")
    // 反向錨點：舊值不得殘留（與上面的正向斷言用同一種查詢方式）
    expect(screen.queryByDisplayValue("採血作業訓練")).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue("課程說明")).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue("護理師")).not.toBeInTheDocument()
  })

  it("查詢被 403 擋下時顯示權限提示，不會卡在轉圈", async () => {
    // #578 把「表單尚未預帶」也納入轉圈條件。該條件若寫成 `courseId !== undefined`
    // 而非 `course !== undefined`，403 / 404 時表單永遠不會預帶 → 轉圈轉到天荒地老，
    // 把下方的錯誤畫面整個蓋掉。這條釘住錯誤畫面仍到得了。
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({ error_code: "ET_COURSE_010", error_message: "無權存取" }, { status: 403 }),
      ),
    )
    renderEditor()

    expect(await screen.findByText("您沒有檢視此課程的權限。課程編輯僅開放教師與管理者。")).toBeInTheDocument()
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
  })

  it("新增模式即可直接新增章節（暫存於畫面，儲存時一次建立）", async () => {
    const user = userEvent.setup()
    renderNewEditor()
    expect(await screen.findByRole("heading", { name: "新增課程" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 尚未儲存課程，章節僅存在於畫面
    expect(await screen.findByDisplayValue("第一章")).toBeInTheDocument()
  })

  it("暫存章節的識別不隨位置改變——刪除第一章後剩下的仍顯示自己的名稱", async () => {
    // 迴歸測試：暫存章節的 id 原本是 `-(index + 1)`，由位置推導。
    // `ChapterRow` 以 chapter_id 當 React key 且內部以 state 保存名稱草稿，
    // 位置一變 key 就對到別人，React 重用同一個元件實例、草稿不更新——
    // 拖拉後畫面「看起來沒動」、刪除後剩下的會顯示被刪者的名稱。
    const user = userEvent.setup()
    renderNewEditor()
    await screen.findByRole("heading", { name: "新增課程" })

    for (const name of ["第一章", "第二章"]) {
      await user.click(screen.getByRole("button", { name: "新增章節" }))
      const input = await screen.findByLabelText("章節名稱")
      await user.click(input)
      await user.paste(name) // 貼上為單次事件，比逐字 type 快很多
      await user.click(screen.getByRole("button", { name: "儲存" }))
      await waitFor(() => expect(screen.queryByLabelText("章節名稱")).not.toBeInTheDocument())
    }
    expect(screen.getByDisplayValue("第一章")).toBeInTheDocument()
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()

    // 暫存章節無學員紀錄可連帶處理，故刪除不跳 confirm
    await user.click(screen.getByRole("button", { name: "刪除章節 第一章" }))

    await waitFor(() => expect(screen.queryByDisplayValue("第一章")).not.toBeInTheDocument())
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()
    // 本條互動數明顯多於其他測試（兩輪對話框開關 + 刪除），全套件滿載時預設 5s 不夠；
    // 拉長 timeout 而非削弱斷言——它驗的是拖拉 / 刪除失效的根因，不宜簡化。
  }, 15000)

  it("新增模式儲存時一次送出課程與暫存章節，並導回列表", async () => {
    const user = userEvent.setup()
    // 用可變容器而非 `let`：`let` 只在 closure 內賦值時，TS 的控制流分析會把
    // closure 外的讀取收斂成 `null`（屬性存取即報 never）。物件屬性不受此收斂影響。
    const captured: { body?: { chapters: string[]; open_start_at: string | null; open_end_at: string | null } } = {}
    server.use(
      http.post("/api/et/courses", async ({ request }) => {
        captured.body = (await request.json()) as NonNullable<typeof captured.body>
        return HttpResponse.json({ course_id: 99, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "新課程")
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))
    // MUI Dialog 關閉有退場動畫，期間仍在 DOM 且對背景設 aria-hidden；
    // 用 findBy* 等它真的消失，否則背景按鈕查不到（同步 getByRole 會失敗）。
    await user.click(await screen.findByRole("button", { name: "儲存草稿" }))

    await waitFor(() => expect(captured.body?.chapters).toEqual(["第一章"]))
    // 起訖時間於草稿允許留空（FR-ET-US3-01）——未填即送 null，不送空字串
    expect(captured.body?.open_start_at).toBeNull()
    expect(captured.body?.open_end_at).toBeNull()
    expect(navigateSpy).toHaveBeenCalledWith("/et/courses")
  })

  it("課程名稱留空時擋下送出並顯示錯誤", async () => {
    const user = userEvent.setup()
    renderNewEditor()
    await user.click(await screen.findByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("請輸入課程名稱")).toBeInTheDocument()
  })

  it("課程描述超過 500 字時擋下送出", async () => {
    const user = userEvent.setup()
    renderEditor()
    const description = await screen.findByRole("textbox", { name: "課程描述" })
    await user.clear(description)
    await user.paste("字".repeat(501))
    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("課程描述不可超過 500 字")).toBeInTheDocument()
  })

  it("非擁有者為檢視模式：顯示提示、無儲存按鈕", async () => {
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "他人的課",
          description: null,
          status: "DRAFT",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 0,
          owner_id: "OTHER",
          owner_name: "林助教",
          is_owner: false,
          audiences: [],
          chapters: [{ chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] }],
        }),
      ),
    )
    renderEditor()
    expect(await screen.findByText(/檢視模式/)).toBeInTheDocument()
    expect(screen.getByText("林助教")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存草稿" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增章節" })).not.toBeInTheDocument()
  })

  it("版本衝突時以對話框呈現而非 snackbar", async () => {
    const user = userEvent.setup()
    server.use(
      http.put("/api/et/courses/:courseId", () =>
        HttpResponse.json(
          { error_code: "ET_LOCK_001", error_message: "資料已被其他使用者修改，請重新載入後再試" },
          { status: 409 },
        ),
      ),
    )
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("內容已被其他裝置變更，請重新整理後再儲存。")).toBeInTheDocument()
  })

  it("已發布課程的既有受訓對象不可移除、不可修改；新增的列照常可刪（#538）", async () => {
    // FR-ET-US3-02：已發布只增不減。鎖的是**伺服器上已存在**的那幾組，不是整區
    const user = userEvent.setup()
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "已發布課",
          description: null,
          status: "PUBLISHED",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 3,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
        }),
      ),
    )
    renderEditor()
    expect(await screen.findByText("已發布課程可新增受訓對象、不可移除既有者")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "第 1 組的單位" })).toBeDisabled()
    expect(screen.getByRole("combobox", { name: "第 1 組的職位" })).toBeDisabled()
    expect(screen.queryByRole("button", { name: "移除第 1 組受訓對象" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "新增受訓對象" }))

    // 成對：新增的第 2 列有刪除鈕、下拉可用——少了這條，「整區鎖死」也會通過上面的斷言
    expect(screen.getByRole("button", { name: "移除第 2 組受訓對象" })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "第 2 組的單位" })).toBeEnabled()
  })

  it("已關閉課程的既有受訓對象可修改、可移除（#586 裁示 A）", async () => {
    // FR-ET-US3-02 只規範草稿與已發布；CLOSED 原本被 `status !== "DRAFT"` 一併掃進鎖定，
    // #586 裁定關閉＝「回到可整理狀態」，教師有權重新定義受訓對象。
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "已關閉課",
          description: null,
          status: "CLOSED",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 3,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
        }),
      ),
    )
    renderEditor()

    expect(await screen.findByDisplayValue("已關閉課")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "第 1 組的單位" })).toBeEnabled()
    expect(screen.getByRole("combobox", { name: "第 1 組的職位" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "移除第 1 組受訓對象" })).toBeInTheDocument()
    // 正反成對、同一種查詢方式：鎖定提示不該出現，而泛用提示該出現
    expect(screen.getByText(/每組為「單位 \+ 職位」/)).toBeInTheDocument()
    expect(screen.queryByText("已發布課程可新增受訓對象、不可移除既有者")).not.toBeInTheDocument()
  })

  describe("受訓對象配對列表（#538）", () => {
    async function pick(user: ReturnType<typeof userEvent.setup>, field: string, option: string) {
      await user.click(screen.getByRole("combobox", { name: field }))
      await user.click(await screen.findByRole("option", { name: option }))
    }

    function capturePut() {
      const captured: { body?: { audiences: { unit_tag_id: number; tag_id: number }[] } } = {}
      server.use(
        http.put("/api/et/courses/:courseId", async ({ request }) => {
          captured.body = (await request.json()) as NonNullable<typeof captured.body>
          return new HttpResponse(null, { status: 204 })
        }),
      )
      return captured
    }

    it("已發布課程新增一組與既有相同的配對：該列仍可改、可刪，並顯示重複訊息（#586）", async () => {
      // 🔴 鎖定是**按值**比對（`lockedKeys.has(audienceKey(row))`），而新增的重複列與既有列
      // 值相同——原本會連新列一起鎖住：兩個下拉 disabled、刪除鈕不渲染，而 `validateForm`
      // 又因 rowErrors 非空擋下儲存 ⇒ 改不了、刪不了、也存不了，只能離開頁面放棄編輯。
      const user = userEvent.setup()
      server.use(
        http.get("/api/et/courses/:courseId", () =>
          HttpResponse.json({
            course_id: 1,
            course_name: "已發布課",
            description: null,
            status: "PUBLISHED",
            open_start_at: null,
            open_end_at: null,
            require_approval: false,
            version: 3,
            owner_id: "U1",
            owner_name: "王教師",
            is_owner: true,
            audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
            chapters: [],
          }),
        ),
      )
      renderEditor()
      await screen.findByDisplayValue("已發布課")

      // 第 1 組是伺服器上既有的 (全單位, 護理師) —— 仍須鎖住
      expect(screen.getByRole("combobox", { name: "第 1 組的單位" })).toBeDisabled()
      expect(screen.queryByRole("button", { name: "移除第 1 組受訓對象" })).not.toBeInTheDocument()

      await user.click(screen.getByRole("button", { name: "新增受訓對象" }))
      await pick(user, "第 2 組的單位", "全單位")
      await pick(user, "第 2 組的職位", "護理師") // 與第 1 組完全相同

      // 重複列不得繼承鎖定：改得動、刪得掉
      expect(screen.getByRole("combobox", { name: "第 2 組的單位" })).toBeEnabled()
      expect(screen.getByRole("combobox", { name: "第 2 組的職位" })).toBeEnabled()
      expect(screen.getByRole("button", { name: "移除第 2 組受訓對象" })).toBeInTheDocument()

      // 按送出鈕才會顯示逐列錯誤；訊息要讓使用者知道為什麼得刪掉這一列
      //
      // ⚠️ #720：已發布課程的動作列沒有「儲存」了，基本資料隨「更新」一起送——所以
      // 驗證也掛在那顆上（`requestApply` 的 `validateBeforeSubmit`）。少了那道驗證，
      // 重複的列會被 `toPayload()` **靜默濾掉**：畫面上還在，按下去卻沒送出去。
      await user.click(screen.getByRole("button", { name: "更新" }))
      expect(await screen.findByText("此組受訓對象已存在")).toBeInTheDocument()

      // 使用者自己刪掉後，錯誤消失、第 1 組仍在且仍鎖定
      await user.click(screen.getByRole("button", { name: "移除第 2 組受訓對象" }))
      await waitFor(() => expect(screen.queryByText("此組受訓對象已存在")).not.toBeInTheDocument())
      expect(screen.getByRole("combobox", { name: "第 1 組的單位" })).toBeDisabled()
    })

    it("新增模式預帶一列空白配對", async () => {
      renderNewEditor()
      expect(await screen.findByRole("combobox", { name: "第 1 組的單位" })).toHaveValue("")
      expect(screen.getByRole("combobox", { name: "第 1 組的職位" })).toHaveValue("")
    })

    it("新增一組配對後送出的 body 帶完整配對；空白列不送", async () => {
      const user = userEvent.setup()
      const captured = capturePut()
      renderEditor()
      await screen.findByDisplayValue("採血作業訓練")
      await user.click(screen.getByRole("button", { name: "新增受訓對象" }))
      await pick(user, "第 2 組的單位", "國防醫學院三軍總醫院")
      await pick(user, "第 2 組的職位", "行政人員")
      await user.click(screen.getByRole("button", { name: "新增受訓對象" })) // 第 3 列留空

      await user.click(screen.getByRole("button", { name: "儲存草稿" }))

      await waitFor(() => expect(captured.body).toBeDefined())
      expect(captured.body?.audiences).toEqual([
        { unit_tag_id: 101, tag_id: 2 },
        { unit_tag_id: 102, tag_id: 3 },
      ])
    })

    it("只選了一欄的配對擋在送出前", async () => {
      const user = userEvent.setup()
      const captured = capturePut()
      renderEditor()
      await screen.findByDisplayValue("採血作業訓練")
      await user.click(screen.getByRole("button", { name: "新增受訓對象" }))
      await pick(user, "第 2 組的單位", "國防醫學院三軍總醫院")

      await user.click(screen.getByRole("button", { name: "儲存草稿" }))

      expect(await screen.findByText("請選擇單位與職位，或刪除此列")).toBeInTheDocument()
      expect(captured.body).toBeUndefined()
    })

    it("發布時兩欄皆空的列也擋下，讓教師決定填或刪（手測回饋）", async () => {
      // 對照組是上方「儲存草稿」那條：同樣留一列空白，草稿照送、發布擋下
      const user = userEvent.setup()
      mockScheduledDraft()
      const captured = capturePut()
      renderEditor()
      await screen.findByDisplayValue("採血作業訓練")
      await user.click(screen.getByRole("button", { name: "新增受訓對象" })) // 第 2 列留空

      await user.click(screen.getByRole("button", { name: "儲存並發布" }))

      // #558：先在視窗列出，關閉後該列才標出來
      const dialog = await screen.findByRole("dialog", { name: "發布課程" })
      expect(await within(dialog).findByText("受訓對象有未選完或重複的列")).toBeInTheDocument()
      await user.click(within(dialog).getByRole("button", { name: "關閉" }))
      expect(await screen.findByText("請選擇單位與職位，或刪除此列")).toBeInTheDocument()
      expect(captured.body).toBeUndefined()

      // 刪掉那列即可發布——錯誤的出路確實存在（視窗退場動畫期間背景仍 aria-hidden，故用 findBy）
      await user.click(await screen.findByRole("button", { name: "移除第 2 組受訓對象" }))
      await user.click(screen.getByRole("button", { name: "儲存並發布" }))

      await waitFor(() => expect(captured.body).toBeDefined())
      expect(captured.body?.audiences).toEqual([{ unit_tag_id: 101, tag_id: 2 }])
    })

    it("受訓對象與其他欄位的錯誤一次全部顯示，不分兩次送出", async () => {
      // code review LOW：受訓對象有錯就提早 return 的話，課程名稱的錯誤要下一次送出才看得到
      const user = userEvent.setup()
      const captured = capturePut()
      renderEditor()
      await user.clear(await screen.findByDisplayValue("採血作業訓練"))
      await user.click(screen.getByRole("button", { name: "新增受訓對象" }))
      await pick(user, "第 2 組的單位", "國防醫學院三軍總醫院")

      await user.click(screen.getByRole("button", { name: "儲存草稿" }))

      expect(await screen.findByText("請選擇單位與職位，或刪除此列")).toBeInTheDocument()
      expect(screen.getByText("請輸入課程名稱")).toBeInTheDocument()
      expect(captured.body).toBeUndefined()
    })

    it("重複的配對擋在送出前", async () => {
      const user = userEvent.setup()
      const captured = capturePut()
      renderEditor()
      await screen.findByDisplayValue("採血作業訓練")
      await user.click(screen.getByRole("button", { name: "新增受訓對象" }))
      await pick(user, "第 2 組的單位", "全單位")
      await pick(user, "第 2 組的職位", "護理師") // 與第 1 組相同

      await user.click(screen.getByRole("button", { name: "儲存草稿" }))

      expect(await screen.findByText("此組受訓對象已存在")).toBeInTheDocument()
      expect(captured.body).toBeUndefined()
    })

    it("單位下拉只有單位、職位下拉只有職位", async () => {
      const user = userEvent.setup()
      renderEditor()
      await screen.findByDisplayValue("採血作業訓練")

      await user.click(screen.getByRole("combobox", { name: "第 1 組的單位" }))

      expect(await screen.findByRole("option", { name: "國防醫學院三軍總醫院" })).toBeInTheDocument()
      expect(screen.queryByRole("option", { name: "行政人員" })).not.toBeInTheDocument()
    })

    it("唯讀模式以後端組好的文字呈現，不顯示下拉", async () => {
      server.use(
        http.get("/api/et/courses/:courseId", () =>
          HttpResponse.json({
            course_id: 1,
            course_name: "他人的課",
            description: null,
            status: "PUBLISHED",
            open_start_at: null,
            open_end_at: null,
            require_approval: false,
            version: 3,
            owner_id: "U9",
            owner_name: "林教師",
            is_owner: false,
            audiences: [{ unit_tag_id: 102, tag_id: 3, label: "國防醫學院三軍總醫院 + 行政人員" }],
            chapters: [],
            invitation_code: null,
          }),
        ),
      )
      renderEditor()
      expect(await screen.findByText("國防醫學院三軍總醫院 + 行政人員")).toBeInTheDocument()
      expect(screen.queryByRole("combobox", { name: "第 1 組的單位" })).not.toBeInTheDocument()
    })
  })
})
